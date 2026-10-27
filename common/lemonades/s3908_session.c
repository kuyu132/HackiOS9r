#include "s3908_session.h"

static unsigned le16(const uint8_t *p) { return p[0] | ((unsigned)p[1] << 8); }

void s3908_session_stop(struct s3908_session *s, struct s3908_event *events, size_t *count)
{
    if (!s || !events || !count) return;
    *count = s3908_input_reset(&s->input, events);
    *s = (struct s3908_session){0};
}

void s3908_session_start(struct s3908_session *s, uint64_t now,
    struct s3908_event *events, size_t *count)
{
    if (!s || !events || !count) return;
    s3908_session_stop(s, events, count);
    s->phase = S3908_IDENTIFY;
    s->last_ms = now;
}

static int fail(struct s3908_session *s, int error,
    struct s3908_event *events, size_t *count)
{
    *count = s3908_input_reset(&s->input, events);
    s->phase = S3908_FAILED;
    s->error = error;
    s->config_size = s->tx_size = s->tx_offset = 0;
    s->waiting = s->retry_wait = 0;
    return error;
}

int s3908_session_poll(struct s3908_session *s, uint64_t now,
    struct s3908_event *events, size_t *count)
{
    if (!s || !events || !count) return S3908_BAD_ARGUMENT;
    *count = 0;
    if (s->phase == S3908_FAILED) return s->error;
    if (s->phase == S3908_STOPPED) return S3908_OK;
    if (now < s->last_ms) return fail(s, S3908_SESSION_PROTOCOL, events, count);
    s->last_ms = now;
    if (s->tx_size && now - s->command_ms >= S3908_SESSION_COMMAND_TIMEOUT_MS)
        return fail(s, S3908_SESSION_TIMEOUT, events, count);
    return S3908_OK;
}

int s3908_session_write(struct s3908_session *s, uint64_t now, size_t limit,
    uint8_t *out, size_t capacity, size_t *length)
{
    if (!s || !out || !length || limit < 3 || capacity < 3) return S3908_BAD_ARGUMENT;
    *length = 0;
    /* Requiring poll(now) ensures a timed-out response is never reused. */
    if (s->phase == S3908_FAILED) return s->error;
    if (s->phase == S3908_STOPPED) return S3908_OK;
    if (now != s->last_ms) return S3908_BAD_ARGUMENT;
    if (s->waiting || s->phase == S3908_READY) return S3908_OK;
    if (s->retry_wait && now - s->retry_ms < 100) return S3908_OK;
    if (s->max_write && limit > s->max_write) limit = s->max_write;
    if (limit > capacity) limit = capacity;
    if (limit < 3) return S3908_SESSION_UNSUPPORTED;
    if (!s->tx_size) {
        size_t payload = 0;
        uint8_t command;
        switch (s->phase) {
        case S3908_IDENTIFY: command = 0x02; break;
        case S3908_APP_INFO: command = 0x20; ++s->app_polls; break;
        case S3908_DISABLE: command = 0x06; payload = 1; break;
        case S3908_SET_CONFIG: command = 0x26; payload = S3908_MAX_CONFIG_SIZE; break;
        case S3908_GET_CONFIG: command = 0x25; break;
        case S3908_ENABLE: command = 0x05; payload = 1; break;
        default: return S3908_SESSION_PROTOCOL;
        }
        s->tx[0] = command;
        s->tx[1] = (uint8_t)payload;
        s->tx[2] = 0;
        for (size_t i = 0; i < payload; ++i)
            s->tx[3 + i] = payload == 1 ? 0x11 :
                (i < S3908_NORMAL_CONFIG_SIZE ? s3908_normal_config[i] : 0);
        s->tx_size = 3 + payload;
        s->tx_offset = 0;
        s->command_ms = now;
        s->retry_wait = 0;
    }
    size_t prefix = s->tx_offset ? 1 : 0;
    size_t bytes = s->tx_size - s->tx_offset;
    if (bytes > limit - prefix) bytes = limit - prefix;
    if (prefix) out[0] = 0x01;
    for (size_t i = 0; i < bytes; ++i) out[prefix + i] = s->tx[s->tx_offset + i];
    s->tx_offset += bytes;
    s->waiting = s->tx_offset == s->tx_size;
    *length = prefix + bytes;
    return S3908_OK;
}

int s3908_session_message(struct s3908_session *s, uint64_t now,
    const uint8_t *frame, size_t size, struct s3908_event *events, size_t *count)
{
    if (!s || !events || !count || !frame) return S3908_BAD_ARGUMENT;
    int result = s3908_session_poll(s, now, events, count);
    if (result != S3908_OK || s->phase == S3908_STOPPED) return result;
    if (size < 5 || size > S3908_SESSION_MAX_MESSAGE || frame[0] != 0xa5 ||
        size != 5u + le16(frame + 2) || frame[size - 1] != 0x5a)
        return fail(s, S3908_BAD_FRAME, events, count);
    unsigned code = frame[1];
    const uint8_t *p = frame + 4;
    size_t n = size - 5;
    if (code == 0x10) return fail(s, S3908_SESSION_RESET, events, count);
    if (code == 0x11) {
        if (s->phase != S3908_READY) return S3908_OK;
        struct s3908_report report;
        result = s3908_decode_normal(s->config, s->config_size, frame, size, &report);
        if (result != S3908_OK) return result;
        if (report.present_mask >> s->max_objects) return S3908_BAD_CONTACT;
        return s3908_input_frame(&s->input, s->config, s->config_size, frame, size,
            s->width, s->height, events, count);
    }
    if (code >= 0x10 && code != 0xff) return S3908_OK; /* bounded unrelated report */
    if ((code == 0 || code == 2) && n == 0) return S3908_OK;
    if (code != 1 || !s->waiting)
        return fail(s, S3908_SESSION_PROTOCOL, events, count);
    switch (s->phase) {
    case S3908_IDENTIFY:
        if (n < 24 || p[1] != 1 || (le16(p + 22) && le16(p + 22) < 3))
            return fail(s, S3908_SESSION_UNSUPPORTED, events, count);
        s->max_write = (uint16_t)le16(p + 22);
        s->phase = S3908_APP_INFO;
        break;
    case S3908_APP_INFO:
        if (n < 48) return fail(s, S3908_BAD_FRAME, events, count);
        if (le16(p + 2) == 1 || le16(p + 2) == 2) {
            if (s->app_polls >= 10) return fail(s, S3908_SESSION_TIMEOUT, events, count);
            s->retry_wait = 1;
            s->retry_ms = now;
            break;
        }
        if (le16(p + 2) != 0 || le16(p + 12) != S3908_MAX_CONFIG_SIZE ||
            le16(p + 36) == 0 || le16(p + 36) > S3908_MAX_CONTACTS ||
            le16(p + 14) < 1 + 12 * le16(p + 36) ||
            le16(p + 32) == 0 || le16(p + 34) == 0)
            return fail(s, S3908_SESSION_UNSUPPORTED, events, count);
        s->width = le16(p + 32) + 1u;
        s->height = le16(p + 34) + 1u;
        s->max_objects = (uint16_t)le16(p + 36);
        s->phase = S3908_DISABLE;
        break;
    case S3908_DISABLE:
    case S3908_SET_CONFIG:
    case S3908_ENABLE:
        if (n) return fail(s, S3908_SESSION_PROTOCOL, events, count);
        s->phase = s->phase == S3908_DISABLE ? S3908_SET_CONFIG :
            (s->phase == S3908_SET_CONFIG ? S3908_GET_CONFIG : S3908_READY);
        break;
    case S3908_GET_CONFIG: {
        struct s3908_report report;
        const uint8_t empty[] = {0xa5,0x11,1,0,0,0x5a};
        if (s3908_decode_normal(p, n, empty, sizeof(empty), &report) != S3908_OK)
            return fail(s, S3908_UNSUPPORTED_CONFIG, events, count);
        for (size_t i = 0; i < n; ++i) s->config[i] = p[i];
        s->config_size = n;
        s->phase = S3908_ENABLE;
        break;
    }
    default: return fail(s, S3908_SESSION_PROTOCOL, events, count);
    }
    s->waiting = 0;
    s->tx_size = s->tx_offset = 0;
    return S3908_OK;
}
