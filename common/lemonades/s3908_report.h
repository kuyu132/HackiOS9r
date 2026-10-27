/* Portable S3908 normal-report decoder. No I/O, allocation, or kernel dependencies.
 * Protocol provenance and transport contract: docs/LEMONADES-S3908.md.
 */
#ifndef LEMONADES_S3908_REPORT_H
#define LEMONADES_S3908_REPORT_H
#include <stddef.h>
#include <stdint.h>

#define S3908_MAX_CONTACTS 10
#define S3908_NORMAL_CONFIG_SIZE 19
#define S3908_MAX_CONFIG_SIZE 128
#define S3908_MAX_FRAME_SIZE (4 + 1 + 12 * S3908_MAX_CONTACTS + 1)

extern const uint8_t s3908_normal_config[S3908_NORMAL_CONFIG_SIZE];

enum s3908_result {
    S3908_OK = 0,
    S3908_BAD_ARGUMENT = -1,
    S3908_UNSUPPORTED_CONFIG = -2,
    S3908_BAD_FRAME = -3,
    S3908_BAD_CONTACT = -4
};

struct s3908_contact {
    uint16_t x, y, width_x, width_y;
    uint8_t classification; /* 0 lift, 1 finger, 2 gloved finger */
    uint8_t edge_width_y, edge_width_x, edge_ratio_y, edge_ratio_x;
};

struct s3908_report {
    uint16_t present_mask, active_mask;
    uint8_t gesture, object_count;
    struct s3908_contact contacts[S3908_MAX_CONTACTS]; /* indexed by controller ID */
};

/* config is the confirmed GET_TOUCH_REPORT_CONFIG payload, not an assumed default.
 * frame is exactly one reassembled TCM message, including header and 0x5a padding.
 * No partial output on error. Inputs and output must not overlap.
 */
int s3908_decode_normal(const uint8_t *config, size_t config_size,
                       const uint8_t *frame, size_t frame_size,
                       struct s3908_report *out);
#endif
