#ifndef LEMONADES_HID_TOUCH_EVENT_H
#define LEMONADES_HID_TOUCH_EVENT_H
#include <CoreFoundation/CoreFoundation.h>
#include "hid_touch.h"
typedef struct __IOHIDEvent *IOHIDEventRef;
/* Creates a retained original IOKit event. Does not send it or commit state.
 * built_in must match the registered service; 0/1 only. No hardware detection. */
IOHIDEventRef lemonades_hid_create_event(const struct lemonades_hid_frame *frame, unsigned built_in);
#endif
