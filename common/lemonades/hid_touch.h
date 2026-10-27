/* Portable touch state -> HID digitizer frame. No I/O or implicit commit.
 * Caller commits next only after its sink accepts the entire frame. On sink
 * failure retain current state for release-all, or discard it only after the
 * old HID service is confirmed removed. Queue loss requires release/resync.
 */
#ifndef LEMONADES_HID_TOUCH_H
#define LEMONADES_HID_TOUCH_H
#include <stdint.h>
#define LEMONADES_HID_CONTACTS 10
#define LEMONADES_HID_RANGE 1u
#define LEMONADES_HID_TOUCH 2u
#define LEMONADES_HID_POSITION 4u
struct lemonades_hid_contact {
    uint32_t identity, x, y;
    uint8_t active;
};
struct lemonades_hid_state {
    uint64_t time;
    uint32_t last_identity;
    struct lemonades_hid_contact contacts[LEMONADES_HID_CONTACTS];
};
struct lemonades_hid_finger {
    uint32_t index, identity, x, y, mask;
    uint8_t active;
};
struct lemonades_hid_frame {
    uint64_t time;
    uint32_t mask, x, y, count;
    uint8_t active;
    struct lemonades_hid_finger fingers[LEMONADES_HID_CONTACTS];
};
enum lemonades_hid_result {
    LEMONADES_HID_OK=0, LEMONADES_HID_INVALID=-1,
    LEMONADES_HID_SEQUENCE=-2, LEMONADES_HID_ID_EXHAUSTED=-3
};
/* type 1/2/3 = queue DOWN/MOVE/UP. Normalized x/y are in [0,65535].
 * Regressing time, duplicate DOWN or MOVE/UP without DOWN are rejected.
 * Input/output objects must not alias. Errors leave both outputs unchanged.
 */
int lemonades_hid_prepare(const struct lemonades_hid_state *state,
    uint64_t time, uint32_t type, uint32_t finger, uint32_t x, uint32_t y,
    struct lemonades_hid_state *next, struct lemonades_hid_frame *frame);
/* An empty state produces count=0 (no event). Time cannot regress. */
int lemonades_hid_release_all(const struct lemonades_hid_state *state, uint64_t time,
    struct lemonades_hid_state *next, struct lemonades_hid_frame *frame);
#endif
