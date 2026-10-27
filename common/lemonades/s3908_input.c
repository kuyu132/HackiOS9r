#include "s3908_input.h"

int s3908_input_frame(struct s3908_input *state, const uint8_t *config, size_t config_size,
    const uint8_t *frame, size_t size, uint32_t width, uint32_t height,
    struct s3908_event events[S3908_MAX_CONTACTS], size_t *count)
{
    struct s3908_report report;
    struct s3908_input next;
    struct s3908_event pending[S3908_MAX_CONTACTS];
    size_t n = 0;
    int result;
    if (!state || !events || !count || width < 2 || height < 2 || width > 65536 || height > 65536)
        return S3908_BAD_ARGUMENT;
    result = s3908_decode_normal(config, config_size, frame, size, &report);
    if (result != S3908_OK) return result;
    next = *state;
    for (unsigned id = 0; id < S3908_MAX_CONTACTS; ++id) {
        uint16_t bit = (uint16_t)(1u << id);
        if (report.active_mask & bit) {
            const struct s3908_contact *c = &report.contacts[id];
            if (c->x >= width || c->y >= height) return S3908_BAD_CONTACT;
            next.x[id] = (uint32_t)c->x * 65535u / (width - 1);
            next.y[id] = (uint32_t)c->y * 65535u / (height - 1);
            pending[n++] = (struct s3908_event){state->active & bit ? 2u : 1u,
                id, next.x[id], next.y[id]};
        } else if (state->active & bit) {
            pending[n++] = (struct s3908_event){3, id, state->x[id], state->y[id]};
        }
    }
    next.active = report.active_mask;
    for (size_t i = 0; i < n; ++i) events[i] = pending[i];
    *state = next;
    *count = n;
    return S3908_OK;
}

size_t s3908_input_reset(struct s3908_input *state, struct s3908_event events[S3908_MAX_CONTACTS])
{
    size_t n = 0;
    if (!state || !events) return 0;
    for (unsigned id = 0; id < S3908_MAX_CONTACTS; ++id) {
        if (state->active & (1u << id))
            events[n++] = (struct s3908_event){3, id, state->x[id], state->y[id]};
    }
    *state = (struct s3908_input){0};
    return n;
}
