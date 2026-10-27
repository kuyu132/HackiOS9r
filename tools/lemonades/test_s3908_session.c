#include "s3908_session.h"
#include "s3908_tcm.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static struct s3908_event events[S3908_MAX_CONTACTS];
static size_t count;
static uint8_t id[24] = {1, 1};
static uint8_t app[48];
static uint8_t config[128];
static const uint8_t touch[] = {0, 0x13, 10,0,20,0,0,0,0,0,0,0,0};

static void put16(uint8_t *p, unsigned v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }

/* Run real generic framing, including every continued-read boundary. */
static int message(struct s3908_session *s, uint64_t now, unsigned code,
    const uint8_t *payload, size_t n, size_t first, size_t limit)
{
    uint8_t frame[S3908_SESSION_MAX_MESSAGE], chunk[S3908_SESSION_MAX_MESSAGE];
    assert(n + 5 <= sizeof(frame));
    frame[0] = 0xa5; frame[1] = (uint8_t)code; put16(frame + 2, (unsigned)n);
    if (n) memcpy(frame + 4, payload, n);
    frame[n + 4] = 0x5a;
    if (first > n + 5) first = n + 5;
    struct s3908_tcm rx = {0};
    int r = s3908_tcm_begin_message(&rx, frame, first);
    while (r == S3908_TCM_MORE) {
        size_t next = s3908_tcm_next_read(&rx, limit);
        assert(next >= 4 && next <= limit);
        chunk[0] = 0xa5; chunk[1] = 3;
        memcpy(chunk + 2, frame + rx.used, next - 2);
        r = s3908_tcm_continue(&rx, chunk, next);
    }
    assert(r == 0 && rx.ready && rx.total == n + 5);
    return s3908_session_message(s, now, rx.frame, rx.total, events, &count);
}

static void command(struct s3908_session *s, uint64_t now, size_t limit,
    unsigned cmd, const uint8_t *payload, size_t n)
{
    uint8_t buffer[131], wire[131];
    size_t length = 0, used = 0;
    assert(s3908_session_poll(s, now, events, &count) == 0 && count == 0);
    while (!s->waiting) {
        assert(s3908_session_write(s, now, limit, buffer, sizeof(buffer), &length) == 0);
        assert(length > 0 && length <= limit && (!s->max_write || length <= s->max_write));
        size_t prefix = used ? 1 : 0;
        if (prefix) assert(buffer[0] == 1);
        assert(used + length - prefix <= sizeof(wire));
        memcpy(wire + used, buffer + prefix, length - prefix);
        used += length - prefix;
    }
    assert(used == n + 3 && wire[0] == cmd && wire[1] == n && wire[2] == 0);
    if (n) assert(memcmp(wire + 3, payload, n) == 0);
    assert(s3908_session_write(s, now, limit, buffer, sizeof(buffer), &length) == 0 && length == 0);
}

static void identify(struct s3908_session *s, size_t limit)
{
    s3908_session_start(s, 0, events, &count);
    command(s, 0, limit, 2, NULL, 0);
    assert(message(s, 1, 1, id, sizeof(id), 4, limit + 1) == 0);
    assert(s->phase == S3908_APP_INFO);
}

static void ready(struct s3908_session *s, size_t first, size_t limit)
{
    identify(s, limit);
    command(s, 1, limit, 0x20, NULL, 0);
    /* Asynchronous touch/diagnostic reports must not complete a command. */
    assert(message(s, 2, 0x11, touch, sizeof(touch), first, limit + 1) == 0 && count == 0);
    assert(s->phase == S3908_APP_INFO && s->waiting);
    assert(message(s, 2, 0x14, id, sizeof(id), first, limit + 1) == 0 && s->waiting);
    assert(message(s, 3, 1, app, sizeof(app), first, limit + 1) == 0);
    assert(s->width == 1080 && s->height == 2400);
    const uint8_t report = 0x11;
    command(s, 3, limit, 6, &report, 1);
    assert(message(s, 4, 1, NULL, 0, first, limit + 1) == 0);
    command(s, 4, limit, 0x26, config, sizeof(config));
    assert(message(s, 5, 1, NULL, 0, first, limit + 1) == 0);
    command(s, 5, limit, 0x25, NULL, 0);
    assert(message(s, 6, 1, config, sizeof(config), first, limit + 1) == 0);
    assert(s->config_size == 128 && s->phase == S3908_ENABLE);
    assert(message(s, 6, 0x11, touch, sizeof(touch), first, limit + 1) == 0 && count == 0);
    command(s, 6, limit, 5, &report, 1);
    assert(message(s, 7, 1, NULL, 0, first, limit + 1) == 0 && s->phase == S3908_READY);
    assert(message(s, 8, 0x11, touch, sizeof(touch), first, limit + 1) == 0);
    assert(count == 1 && events[0].type == 1 && events[0].finger == 3);
}

int main(void)
{
    put16(id + 22, 17); /* controller write limit overrides bus limit */
    put16(app + 12, 128); put16(app + 14, 121);
    put16(app + 32, 1079); put16(app + 34, 2399); put16(app + 36, 10);
    memcpy(config, s3908_normal_config, 19);
    struct s3908_session s = {0};
    for (size_t first = 4; first <= 133; ++first) {
        for (size_t limit = 3; limit <= 40; ++limit) {
            ready(&s, first, limit);
            assert(message(&s, 9, 0x10, id, sizeof(id), first, limit + 1) == S3908_SESSION_RESET);
            assert(count == 1 && events[0].type == 3 && s.phase == S3908_FAILED);
            assert(message(&s, 10, 1, NULL, 0, 4, 4) == S3908_SESSION_RESET && count == 0);
        }
    }
    identify(&s, 3);
    command(&s, 1, 3, 0x20, NULL, 0);
    /* IDLE/BUSY and unrelated reports do not extend command deadline. */
    assert(message(&s, 999, 2, NULL, 0, 4, 4) == 0 && s.waiting);
    assert(s3908_session_poll(&s, 1001, events, &count) == S3908_SESSION_TIMEOUT);
    assert(message(&s, 1002, 1, app, sizeof(app), 4, 4) == S3908_SESSION_TIMEOUT);
    /* Delayed app boot retries are paced and bounded. */
    identify(&s, 3); put16(app + 2, 1);
    for (unsigned attempt = 0; attempt < 10; ++attempt) {
        uint64_t now = 1 + attempt * 100;
        command(&s, now, 3, 0x20, NULL, 0);
        int r = message(&s, now, 1, app, sizeof(app), 4, 4);
        if (attempt == 9) assert(r == S3908_SESSION_TIMEOUT);
        else {
            uint8_t out[131]; size_t n;
            assert(r == 0);
            assert(s3908_session_write(&s, now, 3, out, sizeof(out), &n) == 0 && n == 0);
        }
    }
    put16(app + 2, 0);
    /* Response before a fully transmitted command is a protocol error. */
    identify(&s, 3);
    assert(message(&s, 2, 1, app, sizeof(app), 4, 4) == S3908_SESSION_PROTOCOL);
    /* Readback mismatch never enables reporting. */
    ready(&s, 4, 3);
    s3908_session_stop(&s, events, &count);
    assert(count == 1 && events[0].type == 3 && s.phase == S3908_STOPPED);
    s.phase = S3908_GET_CONFIG; s.last_ms = 0;
    command(&s, 0, 3, 0x25, NULL, 0);
    config[127] = 1;
    assert(message(&s, 1, 1, config, 128, 4, 4) == S3908_UNSUPPORTED_CONFIG);
    config[127] = 0;
    /* Bootloader firmware, short metadata and unsupported contact counts. */
    s3908_session_start(&s, 0, events, &count); command(&s, 0, 3, 2, NULL, 0);
    id[1] = 0x0b;
    assert(message(&s, 1, 1, id, 24, 4, 4) == S3908_SESSION_UNSUPPORTED); id[1] = 1;
    identify(&s, 3); command(&s, 1, 3, 0x20, NULL, 0);
    assert(message(&s, 2, 1, app, 37, 4, 4) == S3908_BAD_FRAME);
    identify(&s, 3); command(&s, 1, 3, 0x20, NULL, 0); put16(app + 36, 11);
    assert(message(&s, 2, 1, app, 48, 4, 4) == S3908_SESSION_UNSUPPORTED); put16(app + 36, 10);
    ready(&s, 4, 3);
    uint8_t bad_touch[sizeof(touch)]; memcpy(bad_touch, touch, sizeof(touch)); bad_touch[1] = 0xff;
    assert(message(&s, 9, 0x11, bad_touch, sizeof(bad_touch), 4, 4) < 0);
    assert(count == 0 && s.input.active == 8);
    assert(s3908_session_poll(&s, 8, events, &count) == S3908_SESSION_PROTOCOL && count == 1);
    /* An error response after READY must release contacts, once only. */
    ready(&s, 4, 3);
    assert(message(&s, 9, 0x0f, NULL, 0, 4, 4) == S3908_SESSION_PROTOCOL && count == 1);
    assert(s3908_session_poll(&s, 10, events, &count) == S3908_SESSION_PROTOCOL && count == 0);
    for (size_t n = 0; n < 48; ++n) {
        identify(&s, 3); command(&s, 1, 3, 0x20, NULL, 0);
        assert(message(&s, 2, 1, app, n, 4, 4) == S3908_BAD_FRAME);
    }
    /* A response halfway through the SET command cannot acknowledge its tail. */
    identify(&s, 3); command(&s, 1, 3, 0x20, NULL, 0);
    assert(message(&s, 2, 1, app, 48, 4, 4) == 0);
    const uint8_t touch_id = 0x11;
    command(&s, 2, 3, 6, &touch_id, 1);
    assert(message(&s, 3, 1, NULL, 0, 4, 4) == 0);
    uint8_t out[131]; size_t out_n;
    assert(s3908_session_write(&s, 3, 3, out, sizeof(out), &out_n) == 0 && out_n == 3);
    assert(!s.waiting && s.tx_offset == 3);
    assert(message(&s, 4, 1, NULL, 0, 4, 4) == S3908_SESSION_PROTOCOL);
    /* Canonical idle header has no meaningful length; oversized data is bounded. */
    struct s3908_tcm rx = {0};
    uint8_t idle[] = {0xa5,0,0xff,0xff};
    assert(s3908_tcm_begin_message(&rx, idle, 4) == 0 && rx.total == 5 && rx.frame[2] == 0);
    idle[1] = 1;
    assert(s3908_tcm_begin_message(&rx, idle, 4) == S3908_BAD_FRAME);
    puts("S3908 session: 4940 split/limit handshakes, report gating, reset releases, timeout/stale response, bounded retries: PASS");
}
