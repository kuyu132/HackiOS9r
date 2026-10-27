#include "s3908_session.h"
#include <sys/lemonades_touch.h>
#include <pexpert/device_tree.h>
#include <assert.h>
#include <string.h>
#include <stdio.h>

static const char *board = "lemonades";
static struct s3908_event posted[100];
static size_t nposted;
int SecureDTLookupEntry(DTEntry from, const char *path, DTEntry *out)
{ (void)from; assert(!strcmp(path, "/chosen")); *out = (DTEntry)1; return kSuccess; }
int SecureDTGetProperty(DTEntry entry, const char *key, const void **out, unsigned *size)
{ (void)entry; assert(!strcmp(key, "hackios,board")); *out = board; *size = (unsigned)strlen(board) + 1; return kSuccess; }
void redwood_touch_post(uint32_t type, uint32_t finger, uint32_t x, uint32_t y)
{ assert(nposted < 100); posted[nposted++] = (struct s3908_event){type, finger, x, y}; }

int main(void)
{
    uint8_t frame[] = {0xa5,0x11,13,0,0, 0x13,0x37,4,0x5f,9,0,0,0,0,0,0,0, 0x5a};
    uint8_t empty[] = {0xa5,0x11,1,0,0,0x5a};
    const uint8_t *config = s3908_normal_config;
    struct s3908_input state = {0}, before;
    struct s3908_event events[10];
    size_t count = 777;
    assert(s3908_input_frame(&state, config, 19, frame, sizeof(frame), 1080, 2400, events, &count) == 0);
    assert(count == 1 && events[0].type == 1 && events[0].finger == 3);
    assert(events[0].x == 65535 && events[0].y == 65535);
    before = state;
    frame[6] = 0x38; /* x=1080 is outside [0,1079] */
    count = 777;
    assert(s3908_input_frame(&state, config, 19, frame, sizeof(frame), 1080, 2400, events, &count) < 0);
    assert(!memcmp(&state, &before, sizeof(state)) && count == 777);
    frame[6] = 0; frame[7] = 0; frame[8] = 0; frame[9] = 0;
    assert(s3908_input_frame(&state, config, 19, frame, sizeof(frame), 1080, 2400, events, &count) == 0);
    assert(count == 1 && events[0].type == 2 && events[0].x == 0 && events[0].y == 0);
    assert(s3908_input_frame(&state, config, 19, empty, sizeof(empty), 1080, 2400, events, &count) == 0);
    assert(count == 1 && events[0].type == 3 && state.active == 0);
    assert(s3908_input_frame(&state, config, 19, empty, sizeof(empty), 1080, 2400, events, &count) == 0 && count == 0);
    state.active = 0x3ff;
    assert(s3908_input_reset(&state, events) == 10 && !state.active);
    for (unsigned i = 0; i < 10; ++i) assert(events[i].type == 3 && events[i].finger == i);
    assert(s3908_input_reset(&state, events) == 0);
    /* Exercise the actual XNU adapter with a mocked queue/DT service. */
    assert(lemonades_touch_frame(config, 19, frame, sizeof(frame), 1080, 2400) == 0);
    assert(nposted == 1 && posted[0].type == 1);
    frame[0] = 0;
    assert(lemonades_touch_frame(config, 19, frame, sizeof(frame), 1080, 2400) < 0 && nposted == 1);
    lemonades_touch_reset();
    assert(nposted == 2 && posted[1].type == 3);
    lemonades_touch_reset(); assert(nposted == 2);
    board = "redwood"; frame[0] = 0xa5;
    assert(lemonades_touch_frame(config, 19, frame, sizeof(frame), 1080, 2400) < 0 && nposted == 2);
    board = "lemonades";
    assert(lemonades_touch_frame(config, 19, frame, sizeof(frame), 1080, 2400) == 0);
    assert(lemonades_touch_frame(config, 19, empty, sizeof(empty), 1080, 2400) == 0);
    assert(nposted == 4 && posted[3].type == 3);
    /* Session entry points retain the board guard and gate the legacy API. */
    uint8_t tx[131]; size_t tx_size = 999;
    board = "redwood";
    assert(lemonades_touch_start(0) < 0);
    assert(lemonades_touch_write(0, 32, tx, sizeof(tx), &tx_size) < 0 && tx_size == 0);
    assert(lemonades_touch_message(0, frame, sizeof(frame)) < 0);
    board = "lemonades";
    assert(lemonades_touch_frame(config, 19, frame, sizeof(frame), 1080, 2400) == 0);
    assert(nposted == 5);
    assert(lemonades_touch_start(0) == 0 && nposted == 6 && posted[5].type == 3);
    assert(lemonades_touch_frame(config, 19, frame, sizeof(frame), 1080, 2400) < 0);
    assert(lemonades_touch_write(0, 32, tx, sizeof(tx), &tx_size) == 0);
    assert(tx_size == 3 && tx[0] == 2 && tx[1] == 0 && tx[2] == 0);
    assert(lemonades_touch_message(1, frame, sizeof(frame)) == 0 && nposted == 6);
    assert(lemonades_touch_poll(1000) == S3908_SESSION_TIMEOUT);
    assert(lemonades_touch_write(1001, 32, tx, sizeof(tx), &tx_size) == S3908_SESSION_TIMEOUT);
    assert(tx_size == 0 && nposted == 6);
    lemonades_touch_reset();
    assert(lemonades_touch_write(2000, 32, tx, sizeof(tx), &tx_size) == 0 && tx_size == 0);
    /* Full session through the actual XNU bridge, not just the portable model. */
    uint8_t identity[24] = {1, 1};
    uint8_t application[48] = {0};
    application[12] = 128; application[14] = 121;
    application[32] = 0x37; application[33] = 4;
    application[34] = 0x5f; application[35] = 9; application[36] = 10;
    const unsigned commands[] = {2, 0x20, 6, 0x26, 0x25, 5};
    assert(lemonades_touch_start(3000) == 0);
    for (unsigned i = 0; i < 6; ++i) {
        uint8_t response[133] = {0xa5, 1, 0, 0};
        size_t n = i == 0 ? 24 : i == 1 ? 48 : i == 4 ? 19 : 0;
        const uint8_t *payload = i == 0 ? identity : i == 1 ? application : config;
        assert(lemonades_touch_write(3000 + i, 256, tx, sizeof(tx), &tx_size) == 0);
        assert(tx_size == (i == 3 ? 131u : (i == 2 || i == 5) ? 4u : 3u));
        assert(tx[0] == commands[i]);
        response[2] = (uint8_t)n;
        memcpy(response + 4, payload, n); response[4 + n] = 0x5a;
        assert(lemonades_touch_message(3000 + i, response, n + 5) == 0 && nposted == 6);
    }
    assert(lemonades_touch_message(3006, frame, sizeof(frame)) == 0);
    assert(nposted == 7 && posted[6].type == 1 && posted[6].finger == 3);
    uint8_t reboot[] = {0xa5, 0x10, 0, 0, 0x5a};
    assert(lemonades_touch_message(3007, reboot, sizeof(reboot)) == S3908_SESSION_RESET);
    assert(nposted == 8 && posted[7].type == 3);
    assert(lemonades_touch_message(3008, frame, sizeof(frame)) == S3908_SESSION_RESET);
    assert(nposted == 8);
    puts("S3908 state transitions, release-all, normalization and XNU queue adapter: PASS");
}
