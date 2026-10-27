#include "s3908_geni.h"
static uint32_t rd(struct s3908_geni *s, uint32_t r) { return s->io.read(s->io.context, r); }
static void wr(struct s3908_geni *s, uint32_t r, uint32_t v) { s->io.write(s->io.context, r, v); }
static void fence(struct s3908_geni *s) { s->io.barrier(s->io.context); }

int s3908_geni_bind(struct s3908_geni *s, const struct s3908_geni_io *io)
{
    if (!s || !io || !io->read || !io->write || !io->barrier) return S3908_GENI_ARGUMENT;
    if (s->phase != SG_UNBOUND && s->phase != SG_FAILED) return S3908_GENI_ARGUMENT;
    struct s3908_geni probe = {0};
    probe.io = *io;
    uint32_t tx = rd(&probe, SG_HW_TX), rx = rd(&probe, SG_HW_RX);
    unsigned td = (tx >> 16) & 63, rt = (rx >> 16) & 63;
    /* Packing for 8 bits, four words, MSB-to-LSB per byte: 7,15,23,31. */
    uint32_t p0 = ((7u << 5) | 0x1e) | (((15u << 5) | 0x1e) << 10);
    uint32_t p1 = ((23u << 5) | 0x1e) | (((31u << 5) | 0x1f) << 10);
    uint32_t required = SG_DONE | SG_TX_WATERMARK | SG_RX_WATERMARK | SG_RX_LAST | (SG_ERRORS & ~(0x3fu << 9));
    if (((rd(&probe, SG_FW) >> 8) & 255) != 3 || rd(&probe, SG_FIFO_DISABLE) ||
        (rd(&probe, SG_DMA) & 1) || rd(&probe, SG_GSI) ||
        (rd(&probe, SG_STATUS) & SG_ACTIVE) ||
        ((tx >> 24) & 63) != 32 || ((rx >> 24) & 63) != 32 || td < 2 || rt < 2 ||
        (rd(&probe, SG_TX_STATUS) & 0x0fffffff) || (rd(&probe, SG_RX_STATUS) & 0x01ffffff) ||
        rd(&probe, SG_TX_PACK0) != p0 || rd(&probe, SG_RX_PACK0) != p0 ||
        rd(&probe, SG_TX_PACK1) != p1 || rd(&probe, SG_RX_PACK1) != p1 ||
        (rd(&probe, SG_IRQ_EN) & required) != required ||
        rd(&probe, SG_RX_WM) == 0 || rd(&probe, SG_RX_WM) >= rt)
        return S3908_GENI_UNPREPARED;
    probe.tx_depth = td; probe.rx_depth = rt; probe.phase = SG_IDLE;
    *s = probe;
    return 0;
}

int s3908_geni_start(struct s3908_geni *s, int reading, const uint8_t *tx,
    size_t length, uint64_t now)
{
    if (!s || (reading != 0 && reading != 1) || !length || length > S3908_GENI_PACKET ||
        (!reading && !tx)) return S3908_GENI_ARGUMENT;
    if (s->phase != SG_IDLE) return S3908_GENI_UNPREPARED;
    if (now < s->last_ms || (rd(s, SG_STATUS) & SG_ACTIVE) ||
        (rd(s, SG_DMA) & 1) || rd(s, SG_GSI) ||
        (rd(s, SG_TX_STATUS) & 0x0fffffff) || (rd(s, SG_RX_STATUS) & 0x01ffffff)) {
        s->phase = SG_FAILED; s->error = S3908_GENI_UNPREPARED;
        return s->error; /* never cancel an engine that was not ours */
    }
    for (size_t i = 0; i < length; ++i) s->data[i] = reading ? 0 : tx[i];
    s->length = length; s->offset = 0; s->reading = reading;
    s->done_seen = s->error = s->recovery = 0;
    s->started_ms = s->phase_ms = s->last_ms = now;
    wr(s, SG_TX_WM, 0);
    wr(s, SG_CLEAR, rd(s, SG_IRQ));
    wr(s, reading ? SG_RX_LEN : SG_TX_LEN, (uint32_t)length);
    fence(s);
    s->phase = SG_RUNNING;
    wr(s, SG_CMD, ((reading ? 2u : 1u) << 27) | (0x4bu << 9));
    if (!reading) wr(s, SG_TX_WM, 1);
    fence(s);
    return S3908_GENI_MORE;
}

static int cancel(struct s3908_geni *s, uint64_t now, int error)
{
    s->error = error;
    s->phase = SG_CANCELLING; s->phase_ms = now;
    wr(s, SG_TX_WM, 0);
    wr(s, SG_CLEAR, rd(s, SG_IRQ));
    wr(s, SG_CTRL, 4);
    fence(s);
    return S3908_GENI_MORE;
}

int s3908_geni_cancel(struct s3908_geni *s, uint64_t now)
{
    if (!s || s->phase == SG_UNBOUND) return S3908_GENI_ARGUMENT;
    if (s->phase == SG_FAILED) return s->error;
    if (s->phase == SG_IDLE) return 0;
    if (s->phase != SG_RUNNING) return S3908_GENI_MORE;
    if (now < s->last_ms) now = s->last_ms;
    s->last_ms = now;
    return cancel(s, now, S3908_GENI_CANCELLED);
}

int s3908_geni_poll(struct s3908_geni *s, uint64_t now)
{
    if (!s || s->phase == SG_UNBOUND) return S3908_GENI_ARGUMENT;
    if (s->phase == SG_FAILED) return s->error;
    if (s->phase == SG_IDLE) return 0;
    if (now < s->last_ms) {
        if (s->phase == SG_RUNNING) return cancel(s, s->last_ms, S3908_GENI_IO);
        now = s->last_ms; /* recovery still requires a progressing clock */
    }
    s->last_ms = now;
    uint32_t irq = rd(s, SG_IRQ);
    s->last_irq = irq;
    if (s->phase == SG_CANCELLING || s->phase == SG_ABORTING) {
        uint32_t wanted = s->phase == SG_CANCELLING ? SG_CANCEL : SG_ABORT;
        if ((irq & wanted) && !(rd(s, SG_STATUS) & SG_ACTIVE)) {
            wr(s, SG_CLEAR, irq); fence(s);
            s->recovery = s->phase == SG_CANCELLING ? 1 : 2;
            s->phase = SG_FAILED;
            return s->error;
        }
        if (now - s->phase_ms >= 50) {
            if (s->phase == SG_CANCELLING) {
                wr(s, SG_CLEAR, irq); wr(s, SG_CTRL, 2); fence(s);
                s->phase = SG_ABORTING; s->phase_ms = now;
            } else { s->recovery = -1; s->phase = SG_FAILED; return s->error; }
        }
        return S3908_GENI_MORE;
    }
    if (irq & SG_ERRORS)
        return cancel(s, now, (irq & SG_NACK) ? S3908_GENI_NACK :
            (irq & SG_ARB) ? S3908_GENI_ARBITRATION : S3908_GENI_IO);
    if (now - s->started_ms >= 600) return cancel(s, now, S3908_GENI_TIMEOUT);
    if (!s->reading && (irq & SG_DONE) && s->offset != s->length)
        return cancel(s, now, S3908_GENI_IO); /* DONE cannot justify unsent data */
    if (s->reading && (irq & (SG_RX_WATERMARK | SG_RX_LAST | SG_DONE))) {
        uint32_t fifo = rd(s, SG_RX_STATUS);
        size_t words = fifo & 0x01ffffff;
        size_t remaining = s->length - s->offset;
        if (words > s->rx_depth || words > (remaining + 3) / 4)
            return cancel(s, now, S3908_GENI_IO);
        for (size_t w = 0; w < words; ++w) {
            size_t bytes = s->length - s->offset;
            if (bytes > 4) bytes = 4;
            if (bytes < 4 && !(irq & (SG_RX_LAST | SG_DONE)))
                return cancel(s, now, S3908_GENI_IO);
            uint32_t value = rd(s, SG_RX_FIFO);
            for (size_t b = 0; b < bytes; ++b) s->data[s->offset++] = (uint8_t)(value >> (8 * b));
        }
    }
    if (!s->reading && (irq & SG_TX_WATERMARK) && !s->done_seen && !(irq & SG_DONE)) {
        size_t words = rd(s, SG_TX_STATUS) & 0x0fffffff;
        if (words > s->tx_depth) return cancel(s, now, S3908_GENI_IO);
        size_t free_words = s->tx_depth - words;
        while (free_words-- && s->offset < s->length) {
            uint32_t value = 0;
            for (unsigned b = 0; b < 4 && s->offset < s->length; ++b)
                value |= (uint32_t)s->data[s->offset++] << (b * 8);
            wr(s, SG_TX_FIFO, value);
        }
        if (s->offset == s->length) wr(s, SG_TX_WM, 0);
    }
    if (irq & SG_DONE) s->done_seen = 1;
    wr(s, SG_CLEAR, irq); fence(s);
    if (s->done_seen) {
        if (s->offset != s->length) return cancel(s, now, S3908_GENI_IO);
        if (!(rd(s, SG_STATUS) & SG_ACTIVE)) {
            if ((rd(s, SG_TX_STATUS) & 0x0fffffff) || (rd(s, SG_RX_STATUS) & 0x01ffffff))
                return cancel(s, now, S3908_GENI_IO);
            s->phase = SG_IDLE;
            return 0;
        }
    }
    return S3908_GENI_MORE;
}
