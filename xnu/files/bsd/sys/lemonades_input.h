/* Versioned full-state input stream. Separate from the legacy 24-byte ABI.
 * /dev/lemonades-touch: exclusive read-only open, 120-byte records. Every record
 * is a complete snapshot; no partial frame interpretation is required.
 * OPEN/OVERFLOW/READ_FAULT or a sequence gap requires release + resynchronization.
 * Short nonzero buffers are EINVAL; empty nonblocking reads are EWOULDBLOCK.
 * dup/fork shares the same stream; the application must keep one consumer.
 * SYNTHETIC is sticky for this boot once a legacy user-space write is observed.
 */
#ifndef LEMONADES_INPUT_H
#define LEMONADES_INPUT_H
#include <stdint.h>
#define LEMONADES_INPUT_DEVICE "/dev/lemonades-touch"
#define LEMONADES_INPUT_VERSION 1u
#define LEMONADES_INPUT_CONTACTS 10u
#define LEMONADES_INPUT_OPEN 1u
#define LEMONADES_INPUT_OVERFLOW 2u
#define LEMONADES_INPUT_READ_FAULT 4u
#define LEMONADES_INPUT_SYNTHETIC 8u
#define LEMONADES_INPUT_RESYNC 7u
#define LEMONADES_INPUT_FLAGS 15u
struct lemonades_input_record {
    uint64_t time, sequence, dropped;
    uint32_t version, flags, active, buttons;
    uint32_t x[LEMONADES_INPUT_CONTACTS], y[LEMONADES_INPUT_CONTACTS];
};
#endif
