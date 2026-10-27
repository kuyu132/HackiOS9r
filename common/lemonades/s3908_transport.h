#ifndef LEMONADES_S3908_TRANSPORT_H
#define LEMONADES_S3908_TRANSPORT_H
#include "s3908_geni.h"
#include "s3908_session.h"
#include "s3908_tcm.h"
struct s3908_transport {
    struct s3908_geni *bus;
    struct s3908_session *session;
    struct s3908_tcm rx;
    unsigned action; /* 0 idle, 1 write, 2 initial read, 3 continuation */
    int running, error;
    uint64_t message_ms;
};
/* Zero initialize. Bus must be bound and externally resynchronized with S3908.
 * Session, transport and bus have one serialized process-context owner.
 * Events must be posted by caller even when a function returns an error.
 */
int s3908_transport_start(struct s3908_transport *, struct s3908_geni *,
    struct s3908_session *, uint64_t, struct s3908_event *, size_t *);
/* At most one bus start or one completion per call. attention is a sampled
 * active-low S3908 IRQ converted to boolean, NOT the GENI completion IRQ.
 * Call on a timer during pending work; no hardware interrupts are installed here.
 */
int s3908_transport_poll(struct s3908_transport *, uint64_t, int attention,
    struct s3908_event *, size_t *);
/* Keep polling after stop until bus cancellation/abort terminates. Do not unmap
 * registers or remove power while bus is running/cancelling/aborting. */
int s3908_transport_stop(struct s3908_transport *, uint64_t, struct s3908_event *, size_t *);
#endif
