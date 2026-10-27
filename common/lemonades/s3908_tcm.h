#ifndef LEMONADES_S3908_TCM_H
#define LEMONADES_S3908_TCM_H
#include "s3908_report.h"
/* Bounded message receive state; dispatch policy lives in s3908_session.
 * Each chunk is one complete I2C read. A caller supplies timeouts/reset and serializes
 * access. Predictive-read bytes beyond the declared message are discarded, as in
 * the pinned Linux driver; this API cannot split a stream of concatenated messages.
 */
#define S3908_TCM_MORE 1
#define S3908_TCM_MAX_MESSAGE 517
struct s3908_tcm {
    uint8_t frame[S3908_TCM_MAX_MESSAGE];
    size_t used, total;
    int ready, synthesized_padding;
};
void s3908_tcm_reset(struct s3908_tcm *state);
/* Original touch-only entry point retains the stricter normal-report bound. */
int s3908_tcm_begin(struct s3908_tcm *state, const uint8_t *chunk, size_t length);
/* Generic bounded response/report framing. IDLE/BUSY headers ignore the length
 * field (as in the controller protocol) and produce a canonical empty message.
 * A standalone CONTINUED_READ header requires explicit resync and is rejected. */
int s3908_tcm_begin_message(struct s3908_tcm *, const uint8_t *, size_t);
/* Size of the next I2C read INCLUDING the A5 03 prefix; chunk_limit >= 4. */
size_t s3908_tcm_next_read(const struct s3908_tcm *state, size_t chunk_limit);
int s3908_tcm_continue(struct s3908_tcm *state, const uint8_t *chunk, size_t length);
#endif
