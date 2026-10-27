/* Prepared GENI FIFO backend, independently implemented from the register
 * interface in the pinned SM8250 driver. See LEMONADES-GENI-TRANSPORT.md.
 * Does NOT enable rails/clocks/pinmux, load SE firmware or map MMIO.
 */
#ifndef LEMONADES_S3908_GENI_H
#define LEMONADES_S3908_GENI_H
#include <stddef.h>
#include <stdint.h>
#define S3908_GENI_PACKET 32
#define S3908_GENI_MORE 1
#define S3908_GENI_ARGUMENT (-20)
#define S3908_GENI_UNPREPARED (-21)
#define S3908_GENI_TIMEOUT (-22)
#define S3908_GENI_NACK (-23)
#define S3908_GENI_ARBITRATION (-24)
#define S3908_GENI_IO (-25)
#define S3908_GENI_CANCELLED (-26)
/* MMIO offsets, relative to an externally mapped and owned SE13 window. */
enum {
    SG_STATUS=0x40, SG_FIFO_DISABLE=0x64, SG_FW=0x68,
    SG_DMA=0x258, SG_TX_PACK0=0x260, SG_TX_PACK1=0x264,
    SG_TX_LEN=0x26c, SG_RX_LEN=0x270, SG_RX_PACK0=0x284, SG_RX_PACK1=0x288,
    SG_CMD=0x600, SG_CTRL=0x604, SG_IRQ=0x610, SG_IRQ_EN=0x614, SG_CLEAR=0x618,
    SG_TX_FIFO=0x700, SG_RX_FIFO=0x780, SG_TX_STATUS=0x800, SG_RX_STATUS=0x804,
    SG_TX_WM=0x80c, SG_RX_WM=0x810, SG_GSI=0xe18,
    SG_HW_TX=0xe24, SG_HW_RX=0xe28
};
#define SG_DONE (1u << 0)
#define SG_CANCEL (1u << 4)
#define SG_ABORT (1u << 5)
#define SG_NACK (1u << 10)
#define SG_ARB (1u << 13)
#define SG_RX_WATERMARK (1u << 26)
#define SG_RX_LAST (1u << 27)
#define SG_TX_WATERMARK (1u << 30)
#define SG_ERRORS ((0x3eu) | (0x3fu << 9) | (3u << 24) | (3u << 28))
#define SG_ACTIVE ((1u << 0) | (1u << 12))
/* Ordered 32-bit device accesses. barrier must order accesses before return.
 * Callbacks cannot sleep, reenter, or throw; MMIO faults require platform handling.
 * The caller guarantees clock/power/pinmux/SE firmware readiness, exclusive
 * ownership, a masked platform IRQ, and a valid device-memory mapping beforehand.
 */
struct s3908_geni_io {
    void *context;
    uint32_t (*read)(void *, uint32_t offset);
    void (*write)(void *, uint32_t offset, uint32_t value);
    void (*barrier)(void *);
};
enum s3908_geni_phase { SG_UNBOUND, SG_IDLE, SG_RUNNING, SG_CANCELLING, SG_ABORTING, SG_FAILED };
struct s3908_geni {
    struct s3908_geni_io io;
    enum s3908_geni_phase phase;
    uint8_t data[S3908_GENI_PACKET];
    size_t length, offset;
    unsigned tx_depth, rx_depth;
    int reading, done_seen, error, recovery; /* recovery: 1 cancel, 2 abort, -1 stuck */
    uint64_t started_ms, phase_ms, last_ms;
    uint32_t last_irq;
};
/* Read-only validation of an ALREADY configured 8-bit/four-byte FIFO engine.
 * On failure no register is written. No bus transaction is started by bind.
 * Rebind after failure only after external controller reset/reinitialization.
 */
int s3908_geni_bind(struct s3908_geni *, const struct s3908_geni_io *);
/* Fixed S3908 address 0x4B, single message with STOP. No DMA/repeated-start/flash.
 * TX copied at start. RX returned in data only after poll returns zero.
 */
int s3908_geni_start(struct s3908_geni *, int reading, const uint8_t *tx, size_t, uint64_t now_ms);
int s3908_geni_poll(struct s3908_geni *, uint64_t now_ms);
/* Request cancellation; keep polling until terminal, retain power and mapping.
 * Every failure is latched even if cancel/abort succeeds; no automatic replay.
 */
int s3908_geni_cancel(struct s3908_geni *, uint64_t now_ms);
#endif
