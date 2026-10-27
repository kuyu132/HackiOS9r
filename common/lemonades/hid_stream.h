#ifndef LEMONADES_HID_STREAM_H
#define LEMONADES_HID_STREAM_H
#include "hid_touch.h"
#include <sys/lemonades_input.h>
struct lemonades_hid_stream {
    struct lemonades_hid_state touch;
    uint64_t sequence, dropped;
    int seen, poisoned;
};
typedef int (*lemonades_hid_sink)(void *,const struct lemonades_hid_frame *);
/* Single owner. Zero-init ONLY for a fresh service. On any sink failure, the
 * stream is poisoned: transport failure may be ambiguous. Retire the old HID
 * service before zero-initializing for a new service and consuming a fresh
 * full snapshot. No blind retries or assumed releases after failed delivery.
 * Buttons are preserved by the queue but this touch-only bridge does not emit
 * keyboard events. Returns 0 accepted, -1 invalid snapshot, -2 poisoned/sink. */
int lemonades_hid_consume(struct lemonades_hid_stream *,const struct lemonades_input_record *,
    lemonades_hid_sink,void *);
#endif
