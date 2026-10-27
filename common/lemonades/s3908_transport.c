#include "s3908_transport.h"

static int halt(struct s3908_transport *s, uint64_t now, int error,
    struct s3908_event *events, size_t *count)
{
    if (!s->error) {
        s->error = error;
        /* Session may already have emitted releases before reporting failure. */
        struct s3908_event released[S3908_MAX_CONTACTS];
        size_t n = 0;
        s3908_session_stop(s->session, released, &n);
        for (size_t i = 0; i < n && *count < S3908_MAX_CONTACTS; ++i)
            events[(*count)++] = released[i];
        s3908_tcm_reset(&s->rx);
    }
    int result = s3908_geni_cancel(s->bus, now);
    if (result != S3908_GENI_MORE) { s->running = 0; return s->error; }
    return S3908_GENI_MORE;
}

int s3908_transport_start(struct s3908_transport *s, struct s3908_geni *bus,
    struct s3908_session *session, uint64_t now, struct s3908_event *events, size_t *count)
{
    if (!s || !bus || !session || !events || !count) return S3908_BAD_ARGUMENT;
    *count = 0;
    if (s->running || bus->phase != SG_IDLE || now < bus->last_ms)
        return S3908_GENI_UNPREPARED;
    *s = (struct s3908_transport){0};
    s->bus = bus; s->session = session; s->running = 1;
    s3908_session_start(session, now, events, count);
    return 0;
}

int s3908_transport_stop(struct s3908_transport *s, uint64_t now,
    struct s3908_event *events, size_t *count)
{
    if (!s || !events || !count) return S3908_BAD_ARGUMENT;
    *count = 0;
    if (!s->running) return s->error;
    return halt(s, now, S3908_GENI_CANCELLED, events, count);
}

int s3908_transport_poll(struct s3908_transport *s, uint64_t now, int attention,
    struct s3908_event *events, size_t *count)
{
    if (!s || !events || !count || (attention != 0 && attention != 1)) return S3908_BAD_ARGUMENT;
    *count = 0;
    if (!s->running) return s->error;
    if (s->error) {
        int result = s3908_geni_poll(s->bus, now);
        if (result == S3908_GENI_MORE) return result;
        s->running = 0;
        return s->error;
    }
    int result = s3908_session_poll(s->session, now, events, count);
    if (result < 0) return halt(s, now, result, events, count);
    if ((s->action >= 2 || (s->rx.used && !s->rx.ready)) && now - s->message_ms >= 1000)
        return halt(s, now, S3908_SESSION_TIMEOUT, events, count);
    if (s->action) {
        result = s3908_geni_poll(s->bus, now);
        /* Release touches as soon as the bus detects a fault, not after abort. */
        if (s->bus->error) return halt(s, now, s->bus->error, events, count);
        if (result == S3908_GENI_MORE) return result;
        if (result < 0) return halt(s, now, result, events, count);
        unsigned action = s->action;
        s->action = 0;
        if (action == 1) return S3908_GENI_MORE;
        result = action == 2 ? s3908_tcm_begin_message(&s->rx, s->bus->data, s->bus->length) :
            s3908_tcm_continue(&s->rx, s->bus->data, s->bus->length);
        if (result < 0) return halt(s, now, result, events, count);
        if (result == S3908_TCM_MORE) return S3908_GENI_MORE;
        result = s3908_session_message(s->session, now, s->rx.frame, s->rx.total, events, count);
        if (result < 0) return halt(s, now, result, events, count);
        s3908_tcm_reset(&s->rx);
        return S3908_GENI_MORE;
    }
    if (s->rx.used && !s->rx.ready) {
        size_t length = s3908_tcm_next_read(&s->rx, S3908_GENI_PACKET);
        result = s3908_geni_start(s->bus, 1, NULL, length, now);
        s->action = 3;
    } else if (attention && !(s->session->tx_size && !s->session->waiting)) {
        s->message_ms = now;
        /* Match the pinned driver's nine-byte predictive first read. */
        result = s3908_geni_start(s->bus, 1, NULL, 9, now);
        s->action = 2;
    } else {
        uint8_t buffer[S3908_GENI_PACKET];
        size_t length = 0;
        result = s3908_session_write(s->session, now, sizeof(buffer), buffer, sizeof(buffer), &length);
        if (result < 0) return halt(s, now, result, events, count);
        if (!length) return 0;
        result = s3908_geni_start(s->bus, 0, buffer, length, now);
        s->action = 1;
    }
    if (result != S3908_GENI_MORE) return halt(s, now, result ? result : S3908_GENI_IO, events, count);
    return S3908_GENI_MORE;
}
