/* Fixed SM8250/OnePlus 9R resource windows. See LEMONADES-TOUCH-PLATFORM.md.
 * Maps prepared hardware; does not acquire power/clock votes or change pinmux.
 */
#include <pexpert/hackios_platform.h>
#include <arm/machine_routines.h>
#include <vm/memory_types.h>
#include <kern/clock.h>
#include <kern/startup.h>
#include <sys/lemonades_touch.h>
#include <sys/lemonades_touch_platform.h>
#include "lemonades/s3908_geni.h"

/* These machine services are hidden from BSD by MACH_KERNEL_PRIVATE in the
 * pinned header. Match its declarations without widening that macro globally. */
extern vm_offset_t ml_io_map_unmappable(vm_offset_t, vm_size_t, uint32_t);
extern void ml_io_unmap(vm_offset_t, vm_size_t);

/* All windows are aligned to and sized for both 4K and 16K kernel pages. */
enum { LTP_WINDOW = 0x4000, LTP_GCC_BRANCH_PA = 0x118000,
    LTP_GCC_VOTE_PA = 0x150000, LTP_GPIO_PA = 0xf524000,
    LTP_SE_PA = 0xa94000, LTP_VOTE = 0x2008,
    LTP_MAHB = 0x4, LTP_SAHB = 0x8, LTP_S5 = 0x5fc };
static const vm_offset_t physical[] = {
    LTP_GCC_BRANCH_PA, LTP_GCC_VOTE_PA, LTP_GPIO_PA, LTP_SE_PA
};
static vm_offset_t mapped[4];
static enum lemonades_touch_platform_state state;
static int fault;

static void barrier(void *unused)
{
    (void)unused;
    __asm__ volatile("dsb sy" ::: "memory");
}

static uint32_t read32(vm_offset_t address)
{
    uint32_t value = *(volatile uint32_t *)address;
    barrier(NULL);
    return value;
}

static uint32_t se_read(void *unused, uint32_t offset)
{
    (void)unused;
    return read32(mapped[3] + offset);
}

static void se_write(void *unused, uint32_t offset, uint32_t value)
{
    (void)unused;
    *(volatile uint32_t *)(mapped[3] + offset) = value;
    barrier(NULL);
}

static uint64_t now_ms(void)
{
    uint64_t ns;
    absolutetime_to_nanoseconds(mach_absolute_time(), &ns);
    return ns / 1000000;
}

static int board_matches(void)
{
    DTEntry chosen;
    const void *value = NULL;
    unsigned size = 0;
    return SecureDTLookupEntry(NULL, "/chosen", &chosen) == kSuccess &&
        SecureDTGetProperty(chosen, "hackios,board", &value, &size) == kSuccess &&
        hackios_decode_board(value, size) == HACKIOS_LEMONADES;
}

static void unmap_all(void)
{
    barrier(NULL);
    for (unsigned i = 4; i; --i) {
        if (mapped[i - 1]) ml_io_unmap(mapped[i - 1], LTP_WINDOW);
        mapped[i - 1] = 0;
    }
}

static int pins_ready(void)
{
    /* SOUTH bank, stride 0x1000: gpio36/37 qup13, reset38 high,
     * attention39 GPIO input. Never write shared TLMM registers. */
    for (unsigned i = 0; i < 2; ++i)
        if (((read32(mapped[2] + i * 0x1000) >> 2) & 15) != 1) return 0;
    uint32_t reset = read32(mapped[2] + 0x2000);
    uint32_t attention = read32(mapped[2] + 0x3000);
    return (reset & ((15u << 2) | (1u << 9))) == (1u << 9) &&
        (read32(mapped[2] + 0x2004) & 2) &&
        !(attention & ((15u << 2) | (1u << 9)));
}

static int clocks_ready(void)
{
    const uint32_t votes = (1u << 27) | (1u << 20) | (1u << 21);
    if ((read32(mapped[1] + LTP_VOTE) & votes) != votes) return 0;
    /* Conservative snapshot: reject CLK_OFF, even for hardware gating. A live
     * branch does not establish its parent frequency or a retained vote. */
    return !((read32(mapped[0] + LTP_MAHB) | read32(mapped[0] + LTP_SAHB) |
        read32(mapped[0] + LTP_S5)) & (1u << 31));
}

int lemonades_touch_platform_open(uint32_t prepared)
{
    if (!board_matches() || prepared != LTP_REQUIRED || startup_phase < STARTUP_SUB_KMEM)
        return LTP_ARGUMENT;
    if (state != LTP_CLOSED || lemonades_touch_bus_quiesced() >= 0) return LTP_BUSY;
    fault = 0;
    /* Map/check clocks and pins before ever reading the SE window. */
    for (unsigned i = 0; i < 4; ++i) {
        mapped[i] = ml_io_map_unmappable(physical[i], LTP_WINDOW, VM_WIMG_IO);
        if (!mapped[i]) { fault = LTP_MAPPING; break; }
        if (i == 1 && !clocks_ready()) { fault = LTP_CLOCK; break; }
        if (i == 2 && !pins_ready()) { fault = LTP_PIN; break; }
    }
    if (!fault) {
        struct s3908_geni_io io = { NULL, se_read, se_write, barrier };
        fault = lemonades_touch_bus_bind(&io, now_ms());
    }
    if (fault) { unmap_all(); return fault; }
    state = LTP_ACTIVE;
    return 0;
}

/* A terminal bus error is distinct from confirmed cancel/abort completion. */
static int finish(int result)
{
    if (result < 0 && !fault) fault = result;
    if (lemonades_touch_bus_quiesced() == 1) {
        if (lemonades_touch_bus_unbind() != 0) {
            state = LTP_QUARANTINED;
            return LTP_STUCK;
        }
        unmap_all();
        state = LTP_CLOSED;
        return fault;
    }
    if (result < 0) {
        state = LTP_QUARANTINED;
        return LTP_STUCK;
    }
    return result;
}

int lemonades_touch_platform_service(void)
{
    if (state == LTP_CLOSED) return LTP_ARGUMENT;
    if (state == LTP_QUARANTINED) return LTP_STUCK;
    int attention = state == LTP_ACTIVE && !(read32(mapped[2] + 0x3004) & 1);
    int result = lemonades_touch_bus_poll(now_ms(), attention);
    if (state == LTP_STOPPING || result < 0) return finish(result);
    return result;
}

int lemonades_touch_platform_close(void)
{
    if (state == LTP_CLOSED) return 0;
    if (state == LTP_QUARANTINED) return LTP_STUCK;
    if (state == LTP_STOPPING) return lemonades_touch_platform_service();
    state = LTP_STOPPING;
    return finish(lemonades_touch_bus_stop(now_ms()));
}

enum lemonades_touch_platform_state lemonades_touch_platform_state(void)
{
    return state;
}
