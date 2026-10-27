#ifndef LEMONADES_S3908_INPUT_H
#define LEMONADES_S3908_INPUT_H
#include "s3908_report.h"
/* Same event numbers/coordinates as sys/redwood_input.h; no kernel dependency. */
struct s3908_event { uint32_t type, finger, x, y; };
struct s3908_input {
    uint16_t active;
    uint32_t x[S3908_MAX_CONTACTS], y[S3908_MAX_CONTACTS];
};
/* A full normal report replaces the active set. No output/state change on error.
 * A serialized worker owns state; never call concurrently or in interrupt context.
 * width/height are the controller coordinate extents confirmed by application info.
 */
int s3908_input_frame(struct s3908_input *state, const uint8_t *config, size_t config_size,
    const uint8_t *frame, size_t size, uint32_t width, uint32_t height,
    struct s3908_event events[S3908_MAX_CONTACTS], size_t *count);
/* Use on controller reset, disconnect or confirmed transport timeout. */
size_t s3908_input_reset(struct s3908_input *state, struct s3908_event events[S3908_MAX_CONTACTS]);
#endif
