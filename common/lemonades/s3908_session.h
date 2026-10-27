/* Independent, bounded TCM initialization policy. No bus, clock or allocation.
 * Protocol source and intentionally unsupported cases: LEMONADES-S3908.md.
 */
#ifndef LEMONADES_S3908_SESSION_H
#define LEMONADES_S3908_SESSION_H
#include "s3908_input.h"
#define S3908_SESSION_TIMEOUT (-5)
#define S3908_SESSION_PROTOCOL (-6)
#define S3908_SESSION_RESET (-7)
#define S3908_SESSION_UNSUPPORTED (-8)
#define S3908_SESSION_MAX_MESSAGE 517
#define S3908_SESSION_COMMAND_TIMEOUT_MS 1000

enum s3908_phase {
    S3908_STOPPED, S3908_IDENTIFY, S3908_APP_INFO, S3908_DISABLE,
    S3908_SET_CONFIG, S3908_GET_CONFIG, S3908_ENABLE, S3908_READY, S3908_FAILED
};
struct s3908_session {
    enum s3908_phase phase;
    struct s3908_input input;
    uint8_t config[S3908_MAX_CONFIG_SIZE], tx[S3908_MAX_CONFIG_SIZE + 3];
    size_t config_size, tx_size, tx_offset;
    uint32_t width, height;
    uint16_t max_write, max_objects;
    uint64_t last_ms, command_ms, retry_ms;
    unsigned app_polls;
    int waiting, retry_wait, error;
};
/* Zero-initialize before first use. Start only AFTER the bus worker has reset or
 * drained the controller: TCM responses contain no transaction ID, so software
 * cannot distinguish a stale OK from a new command's OK. No automatic restart.
 * All calls belong to one serialized worker; buffers must not alias state.
 */
void s3908_session_start(struct s3908_session *, uint64_t now_ms,
    struct s3908_event events[S3908_MAX_CONTACTS], size_t *count);
void s3908_session_stop(struct s3908_session *,
    struct s3908_event events[S3908_MAX_CONTACTS], size_t *count);
int s3908_session_poll(struct s3908_session *, uint64_t now_ms,
    struct s3908_event events[S3908_MAX_CONTACTS], size_t *count);
/* Returns one whole bus write (command/length or CONTINUE_WRITE prefix).
 * Call poll first. The caller must immediately write ALL returned bytes once;
 * on short/failed write, stop and resynchronize; never retry a consumed chunk.
 * length=0 means waiting/ready/stopped. bus_limit and capacity must be >=3.
 */
int s3908_session_write(struct s3908_session *, uint64_t now_ms, size_t bus_limit,
    uint8_t *out, size_t capacity, size_t *length);
/* Exactly one fully reassembled message, including A5 header and 5A padding.
 * Reports may interleave with a pending response; only READY emits touch events.
 * Reset, command failure, framing failure and timeout release active contacts.
 * Bad touch payload leaves contacts unchanged; worker may stop on repeated errors.
 */
int s3908_session_message(struct s3908_session *, uint64_t now_ms,
    const uint8_t *frame, size_t size,
    struct s3908_event events[S3908_MAX_CONTACTS], size_t *count);
#endif
