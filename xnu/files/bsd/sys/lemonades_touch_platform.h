#ifndef LEMONADES_TOUCH_PLATFORM_H
#define LEMONADES_TOUCH_PLATFORM_H
#include <stdint.h>

/* Kernel-only prepared-resource lease contract, NOT hardware detection or a
 * boot argument. The platform owner must establish ALL of these and keep them
 * valid until state is CLOSED. No caller exists in the automatic boot path yet.
 * One serialized process-context worker owns ALL touch APIs; no concurrent raw
 * bus/session calls. Call after VM startup and redwood_input_init().
 */
#define LTP_EXCLUSIVE       (1u << 0) /* no firmware/other OS/driver owns SE13 */
#define LTP_POWER_HELD      (1u << 1) /* rails and interconnect votes retained */
#define LTP_CLOCKS_HELD     (1u << 2) /* parent/rate/branch votes retained */
#define LTP_PINS_HELD       (1u << 3) /* mux and GPIO ownership retained */
#define LTP_IRQS_MASKED     (1u << 4) /* GENI and touch platform IRQs masked */
#define LTP_RESYNCHRONIZED  (1u << 5) /* firmware/FIFO prepared; TCM reset/drain */
#define LTP_REQUIRED 0x3fu
enum lemonades_touch_platform_state { LTP_CLOSED, LTP_ACTIVE, LTP_STOPPING, LTP_QUARANTINED };
enum { LTP_ARGUMENT = -40, LTP_MAPPING = -41, LTP_CLOCK = -42,
    LTP_PIN = -43, LTP_STUCK = -44, LTP_BUSY = -45 };
/* Open performs read-only validation; first service may start an I2C command.
 * Flags attest caller obligations; register snapshots cannot prove those.
 * Poll regularly (e.g. 1 ms), including during asynchronous close/recovery.
 * Negative service/close return is NOT permission to release the lease:
 * only CLOSED permits that. QUARANTINED requires external platform recovery;
 * this API intentionally has no force-unmap or automatic reopen path.
 */
int lemonades_touch_platform_open(uint32_t prepared);
int lemonades_touch_platform_service(void);
int lemonades_touch_platform_close(void);
enum lemonades_touch_platform_state lemonades_touch_platform_state(void);
#endif
