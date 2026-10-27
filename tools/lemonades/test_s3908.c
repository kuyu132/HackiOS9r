#include "s3908_report.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

/* Hand-encoded protocol vector: slot 3, finger; x=0x1234 y=0x5678;
 * widths=0xabc/0xdef; grip bytes=1/2/3/4. Not a real hardware capture.
 */
static const uint8_t sample[] = {
    0xa5, 0x11, 13, 0, 1,
    0x13, 0x34, 0x12, 0x78, 0x56, 0xbc, 0xfa, 0xde, 1, 2, 3, 4,
    0x5a
};

static void rejected(const uint8_t *config, size_t cs, const uint8_t *frame, size_t fs, int expected)
{
    struct s3908_report out, before;
    memset(&out, 0x7b, sizeof(out));
    memcpy(&before, &out, sizeof(out));
    assert(s3908_decode_normal(config, cs, frame, fs, &out) == expected);
    assert(!memcmp(&before, &out, sizeof(out)));
}

static void vectors(void)
{
    struct s3908_report out;
    uint8_t config[128] = {16,8,1,6,4,7,4,8,16,9,16,11,12,12,12,203,32,3,0};
    uint8_t frame[S3908_MAX_FRAME_SIZE + 12] = {0xa5, 0x11, 1, 0, 0, 0x5a};
    assert(s3908_decode_normal(config, sizeof(config), sample, sizeof(sample), &out) == S3908_OK);
    assert(out.gesture == 1 && out.object_count == 1 && out.active_mask == 8 && out.present_mask == 8);
    const struct s3908_contact *c = &out.contacts[3];
    assert(c->classification == 1 && c->x == 0x1234 && c->y == 0x5678);
    assert(c->width_x == 0xabc && c->width_y == 0xdef);
    assert(c->edge_width_y == 1 && c->edge_width_x == 2 && c->edge_ratio_y == 3 && c->edge_ratio_x == 4);

    /* Empty active-object list releases all previous slots in the future adapter. */
    assert(s3908_decode_normal(config, 19, frame, 6, &out) == S3908_OK);
    assert(out.active_mask == 0 && out.object_count == 0 && out.contacts[3].x == 0);
    for (size_t n = 0; n < sizeof(sample); ++n)
        rejected(config, 19, sample, n, S3908_BAD_FRAME);
    rejected(NULL, 19, sample, sizeof(sample), S3908_BAD_ARGUMENT);
    rejected(config, 19, NULL, 0, S3908_BAD_ARGUMENT);
    assert(s3908_decode_normal(config, 19, sample, sizeof(sample), NULL) == S3908_BAD_ARGUMENT);
    rejected(config, 18, sample, sizeof(sample), S3908_UNSUPPORTED_CONFIG);
    rejected(config, 129, sample, sizeof(sample), S3908_UNSUPPORTED_CONFIG);
    config[19] = 1;
    rejected(config, 128, sample, sizeof(sample), S3908_UNSUPPORTED_CONFIG);
    config[19] = 0;
    config[8] = 12;
    rejected(config, 128, sample, sizeof(sample), S3908_UNSUPPORTED_CONFIG);
    config[8] = 16;

    memcpy(frame, sample, sizeof(sample));
    frame[0] = 0;
    rejected(config, 19, frame, sizeof(sample), S3908_BAD_FRAME);
    frame[0] = 0xa5; frame[1] = 3; /* continued-read chunk is not a reassembled report */
    rejected(config, 19, frame, sizeof(sample), S3908_BAD_FRAME);
    frame[1] = 0x11; frame[3] = 255;
    rejected(config, 19, frame, sizeof(sample), S3908_BAD_FRAME);
    frame[3] = 0; frame[17] = 0;
    rejected(config, 19, frame, sizeof(sample), S3908_BAD_FRAME);
    frame[17] = 0x5a; frame[5] = 0x1a;
    rejected(config, 19, frame, sizeof(sample), S3908_BAD_CONTACT);
    frame[5] = 0x33;
    rejected(config, 19, frame, sizeof(sample), S3908_BAD_CONTACT);
    frame[5] = 0x23;
    assert(s3908_decode_normal(config, 19, frame, sizeof(sample), &out) == S3908_OK);
    assert(out.contacts[3].classification == 2 && out.active_mask == 8);
    frame[5] = 0x03;
    assert(s3908_decode_normal(config, 19, frame, sizeof(sample), &out) == S3908_OK);
    assert(out.active_mask == 0 && out.present_mask == 8);

    for (unsigned i = 0; i < 10; ++i) {
        memcpy(frame + 5 + 12 * i, sample + 5, 12);
        frame[5 + 12 * i] = (uint8_t)(0x10 + i);
    }
    frame[2] = 121; frame[125] = 0x5a;
    assert(s3908_decode_normal(config, 19, frame, 126, &out) == S3908_OK);
    assert(out.object_count == 10 && out.active_mask == 0x3ff);
    frame[5 + 12 * 9] = 0x10; /* duplicate slot, after nine otherwise valid records */
    rejected(config, 19, frame, 126, S3908_BAD_CONTACT);
    rejected(config, 19, frame, sizeof(frame), S3908_BAD_FRAME);
    frame[2] = 2; frame[6] = 0x5a;
    rejected(config, 19, frame, 7, S3908_BAD_FRAME); /* partial object */
    puts("S3908 protocol vectors, malformed frames and transactional output: PASS");
}

static uint32_t seed = 0x39089;
static uint32_t random32(void)
{
    seed ^= seed << 13; seed ^= seed >> 17; seed ^= seed << 5;
    return seed;
}

static void mutations(void)
{
    uint8_t bytes[160], config[128];
    struct s3908_report out, before;
    for (unsigned iteration = 0; iteration < 100000; ++iteration) {
        size_t length = random32() % (sizeof(bytes) + 1);
        for (size_t i = 0; i < sizeof(bytes); ++i) bytes[i] = (uint8_t)random32();
        memset(config, 0, sizeof(config));
        memcpy(config, s3908_normal_config, S3908_NORMAL_CONFIG_SIZE);
        if (iteration & 1) {
            memcpy(bytes, sample, sizeof(sample));
            length = sizeof(sample);
            bytes[random32() % length] = (uint8_t)random32();
        }
        if (iteration % 3 == 0) config[random32() % sizeof(config)] = (uint8_t)random32();
        memset(&out, 0xac, sizeof(out));
        memcpy(&before, &out, sizeof(out));
        int result = s3908_decode_normal(config, sizeof(config), bytes, length, &out);
        if (result != S3908_OK) assert(!memcmp(&before, &out, sizeof(out)));
        else {
            assert(out.object_count <= 10 && !(out.present_mask & ~0x3ff));
            assert((out.active_mask & out.present_mask) == out.active_mask);
        }
    }
    puts("S3908 deterministic malformed-input mutations: 100000 PASS");
}

int main(void)
{
    vectors();
    mutations();
    return 0;
}
