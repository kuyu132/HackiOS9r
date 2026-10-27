/*
 * /dev/redwood-touch: a queue of touch samples (see sys/redwood_input.h).
 */
#include <kern/clock.h>
#include <kern/locks.h>
#include <kern/thread_call.h>
#include <libkern/libkern.h>
#include <miscfs/devfs/devfs.h>
#include <sys/conf.h>
#include <sys/errno.h>
#include <sys/fcntl.h>
#include <sys/filio.h>
#include <sys/vnode.h>
#include "lemonades_input_queue.h"
#include <sys/proc.h>
#include <sys/select.h>
#include <sys/redwood_input.h>
#include <sys/systm.h>
#include <sys/uio.h>
#include <pexpert/pexpert.h>

#define TOUCH_QUEUE     512             /* records; a power of two */

/*
 * Boot-arg touch_lat=1: for measuring how long a touch takes to reach the panel, a line for every
 * sample posted ("tl: p TYPE FINGER X Y at US", the time in microseconds of mach_absolute_time),
 * to be matched with the window server's lines about reading it (userland/src/inject.c), drawing
 * (eagl.c) and the display driver's about the frame (MiniIOMobileFramebuffer.cpp): see
 * tools/latency.py.
 */
static uint32_t touch_lat = 2;          /* 2: not yet looked up */

extern void loader_log_line(const char *line);

/*
 * A "tl:" line, for the kernel's drivers: into the loader's log as it is written -- the kernel's own
 * log keeps only the last of a run, and a live look at the loader's (XL_FOLLOW) then misses nothing.
 */
void redwood_tl(const char *format, ...) __printflike(1, 2);

void
redwood_tl(const char *format, ...)
{
	char line[192];
	va_list list;

	va_start(list, format);
	vsnprintf(line, sizeof(line), format, list);
	va_end(list);
	loader_log_line(line);
}

static bool
latency_lines(void)
{
	if (touch_lat == 2) {
		uint32_t on = 0;

		touch_lat = PE_parse_boot_argn("touch_lat", &on, sizeof(on)) && on != 0;
	}
	return touch_lat != 0;
}

static LCK_GRP_DECLARE(touch_lck_grp, "redwood-touch");
static LCK_MTX_DECLARE(touch_lock, &touch_lck_grp);
static struct redwood_touch touch_queue[TOUCH_QUEUE];
static struct lemonades_input_queue input_v1;
/* Protected by touch_lock, including select registration and wakeup. */
static struct selinfo input_select;
static uint32_t touch_head, touch_tail;        /* read from head, add at tail */

/*
 * The way out when nothing else is at hand: five fingers held on the screen for a second and a
 * half end the run -- control goes back to the loader, as when loader_return_after expires.
 * Only a driver's fingers count, not samples a program writes to the device.
 */
#define EXIT_FINGERS    5
#define EXIT_HOLD_MS    1500

extern void loader_return(void);

static thread_call_t exit_call;
static uint32_t fingers_down;           /* one bit for each finger a driver says is down */

static void
exit_hold_elapsed(__unused thread_call_param_t p0, __unused thread_call_param_t p1)
{
	printf("\n--- %d fingers held on the screen for %d ms: back to the loader ---\n", EXIT_FINGERS, EXIT_HOLD_MS);
	redwood_adreno_stop();
	loader_return();
}

/* With touch_lock held. */
static void
count_fingers(uint32_t type, uint32_t finger)
{
	int before = __builtin_popcount(fingers_down), now;
	uint64_t deadline;

	if (finger >= 32 || exit_call == NULL || (type != REDWOOD_TOUCH_DOWN && type != REDWOOD_TOUCH_UP)) {
		return;
	}
	if (type == REDWOOD_TOUCH_DOWN) {
		fingers_down |= 1u << finger;
	} else {
		fingers_down &= ~(1u << finger);
	}
	now = __builtin_popcount(fingers_down);
	if (now >= EXIT_FINGERS && before < EXIT_FINGERS) {
		clock_interval_to_deadline(EXIT_HOLD_MS, NSEC_PER_MSEC, &deadline);
		thread_call_enter_delayed(exit_call, deadline);
	} else if (now < EXIT_FINGERS && before >= EXIT_FINGERS) {
		thread_call_cancel(exit_call);
	}
}

static void
touch_post(uint32_t type, uint32_t finger, uint32_t x, uint32_t y, bool from_driver)
{
	struct redwood_touch *t;

	lck_mtx_lock(&touch_lock);
	if (touch_tail - touch_head == TOUCH_QUEUE) {
		touch_head++;                   /* nobody reads: drop the oldest */
	}
	t = &touch_queue[touch_tail++ % TOUCH_QUEUE];
	t->time = mach_absolute_time();
	if (latency_lines()) {
		uint64_t ns;

		absolutetime_to_nanoseconds(t->time, &ns);
		redwood_tl("tl: p %u %u %u %u at %llu\n", type, finger, x, y, ns / 1000);
	}
	t->type = type;
	t->finger = finger;
	t->x = x > 65535 ? 65535 : x;
	t->y = y > 65535 ? 65535 : y;
	(void)lemonades_input_post(&input_v1, t->time, type, finger, t->x, t->y, !from_driver);
	selwakeup(&input_select);
	if (from_driver) {
		count_fingers(type, finger);
	}
	lck_mtx_unlock(&touch_lock);
	wakeup(&touch_queue);
	wakeup(&input_v1);
}

void
redwood_touch_post(uint32_t type, uint32_t finger, uint32_t x, uint32_t y)
{
	touch_post(type, finger, x, y, true);
}

static int
touch_open(dev_t dev, int flags, __unused int devtype, __unused struct proc *p)
{
	if (minor(dev) == 1) {
		if (!(flags & FREAD) || (flags & FWRITE)) return EACCES;
		lck_mtx_lock(&touch_lock);
		int error = input_v1.exhausted ? EOVERFLOW : (input_v1.opened || input_v1.reading) ? EBUSY : 0;
		if (!error) {
			input_v1.opened = 1;
			lemonades_input_resync(&input_v1, mach_absolute_time(), LEMONADES_INPUT_OPEN);
			if (input_v1.exhausted) { input_v1.opened = 0; error = EOVERFLOW; }
		}
		lck_mtx_unlock(&touch_lock);
		return error;
	}
	return 0;
}

static int
touch_close(dev_t dev, __unused int flags, __unused int devtype, __unused struct proc *p)
{
	if (minor(dev) == 1) {
		lck_mtx_lock(&touch_lock);
		input_v1.opened = 0;
		selthreadclear(&input_select);
		lck_mtx_unlock(&touch_lock);
		wakeup(&input_v1);
	}
	return 0;
}

static int
snapshot_read(struct uio *uio, int ioflag)
{
	struct lemonades_input_record record;
	int error = 0;
	if (uio_resid(uio) == 0) return 0;
	if (uio_resid(uio) < (user_ssize_t)sizeof(record)) return EINVAL;
	lck_mtx_lock(&touch_lock);
	if (input_v1.reading) { lck_mtx_unlock(&touch_lock); return EBUSY; }
	input_v1.reading = 1;
	while (!input_v1.count && input_v1.opened && !input_v1.exhausted) {
		if (ioflag & IO_NDELAY) { error = EWOULDBLOCK; break; }
		error = msleep(&input_v1, &touch_lock, PZERO | PCATCH, "lemonades-touch", NULL);
		if (error) break;
	}
	if (!error && (!input_v1.opened || input_v1.exhausted))
		error = input_v1.exhausted ? EOVERFLOW : ENXIO;
	/* One complete snapshot per read. No lock held over faulting copyout.
	 * A copy fault invalidates all pending deltas and schedules a fresh snapshot. */
	if (!error && lemonades_input_pop(&input_v1, &record)) {
		lck_mtx_unlock(&touch_lock);
		error = uiomove((caddr_t)&record, sizeof(record), uio);
		lck_mtx_lock(&touch_lock);
		if (error) {
			if (input_v1.current.dropped == UINT64_MAX) input_v1.exhausted = 1;
			else input_v1.current.dropped++; /* record removed before copyout */
			lemonades_input_resync(&input_v1, mach_absolute_time(), LEMONADES_INPUT_READ_FAULT);
			selwakeup(&input_select);
		}
	}
	input_v1.reading = 0;
	lck_mtx_unlock(&touch_lock);
	return error;
}

static int
touch_read(dev_t dev, struct uio *uio, int ioflag)
{
	struct redwood_touch t;
	int error = 0, moved = 0;

	if (minor(dev) == 1) return snapshot_read(uio, ioflag);
	lck_mtx_lock(&touch_lock);
	while (touch_head == touch_tail) {
		error = msleep(&touch_queue, &touch_lock, PZERO | PCATCH, "redwood-touch", NULL);
		if (error) {
			lck_mtx_unlock(&touch_lock);
			return error;
		}
	}
	while (touch_head != touch_tail && uio_resid(uio) >= (user_ssize_t)sizeof(t)) {
		t = touch_queue[touch_head++ % TOUCH_QUEUE];
		lck_mtx_unlock(&touch_lock);
		error = uiomove((caddr_t)&t, sizeof(t), uio);
		lck_mtx_lock(&touch_lock);
		if (error) {
			break;
		}
		moved++;
	}
	lck_mtx_unlock(&touch_lock);
	return moved ? 0 : error;
}

static int
touch_write(dev_t dev, struct uio *uio, __unused int ioflag)
{
	struct redwood_touch t;
	int error = 0;

	if (minor(dev) == 1) return EACCES;
	while (uio_resid(uio) >= (user_ssize_t)sizeof(t)) {
		error = uiomove((caddr_t)&t, sizeof(t), uio);
		if (error) {
			break;
		}
		if (t.type < REDWOOD_TOUCH_DOWN || t.type > REDWOOD_BUTTON_UP) {
			return EINVAL;
		}
		touch_post(t.type, t.finger, t.x, t.y, false);
	}
	return error;
}

static int
touch_ioctl(dev_t dev, u_long command, __unused caddr_t data, __unused int flags, __unused struct proc *p)
{
	/* fcntl(F_SETFL) issues FIONBIO and FIOASYNC when changing flags. read receives
	 * IO_NDELAY from those flags; no per-device nonblocking state is needed. */
	if (minor(dev) != 1) return ENODEV;
	if (command == FIONBIO) return 0;
	/* No SIGIO delivery is implemented; disabling it must still succeed. */
	if (command == FIOASYNC) return *(int *)data ? ENOTSUP : 0;
	return ENOTTY;
}

static int
touch_select(dev_t dev, int which, void *wql, struct proc *p)
{
	if (minor(dev) != 1) return ENODEV; /* legacy endpoint has no select contract */
	if (which != FREAD) return 0;
	lck_mtx_lock(&touch_lock);
	int ready = input_v1.count || input_v1.exhausted || !input_v1.opened;
	if (!ready) selrecord(p, &input_select, wql);
	lck_mtx_unlock(&touch_lock);
	return ready ? 1 : 0;
}

static const struct cdevsw touch_cdevsw = {
	.d_open = touch_open, .d_close = touch_close, .d_read = touch_read, .d_write = touch_write,
	.d_ioctl = touch_ioctl, .d_stop = eno_stop, .d_reset = eno_reset, .d_select = touch_select,
	.d_mmap = eno_mmap, .d_strategy = eno_strat, .d_type = 0
};

void
redwood_input_init(void)
{
	int major = cdevsw_add(-1, &touch_cdevsw);

	if (major < 0 || devfs_make_node(makedev(major, 0), DEVFS_CHAR, UID_ROOT, GID_WHEEL, 0666, "redwood-touch") == NULL) {
		printf("redwood-touch: cannot create the device\n");
	}
	if (major >= 0 && devfs_make_node(makedev(major, 1), DEVFS_CHAR, UID_ROOT, GID_WHEEL, 0600, "lemonades-touch") == NULL) {
		printf("lemonades-touch: cannot create the snapshot device\n");
	}
	exit_call = thread_call_allocate(exit_hold_elapsed, NULL);
	redwood_cpufreq_init();
	redwood_virtio_input_init();
	redwood_goodix_init();
	redwood_buttons_init();
	redwood_battery_init();
	redwood_ufs_init();
	redwood_net_init();
	redwood_adreno_init();
	redwood_wifi_init();
	redwood_adsp_init();
}
