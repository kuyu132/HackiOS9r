#ifndef LEMONADES_TOUCH_H
#define LEMONADES_TOUCH_H
#include <stddef.h>
#include <stdint.h>
/* Serialized transport-worker API, after redwood_input_init() created the queue.
 * Return values are enum s3908_result. No I2C transactions or implicit defaults.
 */
int lemonades_touch_frame(const unsigned char *, size_t, const unsigned char *, size_t, unsigned, unsigned);
void lemonades_touch_reset(void);
/* Session API for the future bus worker: see s3908_session.h for resync,
 * timing, write-completion and complete-message contracts. No automatic I/O. */
int lemonades_touch_start(uint64_t now_ms);
int lemonades_touch_poll(uint64_t now_ms);
int lemonades_touch_write(uint64_t now_ms, size_t limit, unsigned char *, size_t, size_t *);
int lemonades_touch_message(uint64_t now_ms, const unsigned char *, size_t);
/* Prepared FIFO interface. No resource initialization or IRQ installation.
 * Bind requires external reset/resync and live, exclusive MMIO resources.
 * After bind, raw frame/session interfaces are disabled to preserve one owner.
 * Stop releases touches immediately; continue bus_poll through cancel/abort.
 * Keep resources alive until recovery succeeds; stuck recovery needs platform
 * reset. Rebind only after that external reset/reinitialization and TCM resync. */
struct s3908_geni_io;
int lemonades_touch_bus_bind(const struct s3908_geni_io *, uint64_t);
int lemonades_touch_bus_poll(uint64_t, int attention);
int lemonades_touch_bus_stop(uint64_t);
/* 1: stopped and confirmed quiescent; 0: active or quiescence unconfirmed.
 * An error return from bus_poll alone NEVER authorizes power removal/unmapping. */
int lemonades_touch_bus_quiesced(void);
/* Detach only after confirmed quiescence, before releasing mapped resources. */
int lemonades_touch_bus_unbind(void);
#endif
