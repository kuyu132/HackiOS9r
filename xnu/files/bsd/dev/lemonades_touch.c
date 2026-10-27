/* S3908 -> existing touch/HID queue. Optional prepared-GENI worker adapter.
 * Call only from one serialized process-context transport worker, after querying
 * GET_TOUCH_REPORT_CONFIG and application coordinate bounds from the controller.
 */
#include <pexpert/hackios_platform.h>
#include <sys/types.h>
#include <stdbool.h>
#include <sys/redwood_input.h>
#include <sys/lemonades_touch.h>
#include "lemonades/s3908_transport.h"

static struct s3908_session touch_session;
static struct s3908_geni touch_bus;
static struct s3908_transport touch_transport;

static int is_lemonades(void)
{
    DTEntry chosen;
    const void *value = NULL;
    unsigned int size = 0;
    return SecureDTLookupEntry(NULL, "/chosen", &chosen) == kSuccess &&
        SecureDTGetProperty(chosen, "hackios,board", &value, &size) == kSuccess &&
        hackios_decode_board(value, size) == HACKIOS_LEMONADES;
}

static void post(const struct s3908_event *events, size_t count)
{
    for (size_t i = 0; i < count; ++i)
        redwood_touch_post(events[i].type, events[i].finger, events[i].x, events[i].y);
}

int lemonades_touch_frame(const unsigned char *config, size_t config_size,
    const unsigned char *frame, size_t size, unsigned width, unsigned height)
{
    struct s3908_event events[S3908_MAX_CONTACTS];
    size_t count = 0;
    if (!is_lemonades() || touch_transport.bus || touch_session.phase != S3908_STOPPED) return S3908_BAD_ARGUMENT;
    int status = s3908_input_frame(&touch_session.input, config, config_size, frame, size,
        width, height, events, &count);
    if (status == S3908_OK) post(events, count);
    return status;
}

void lemonades_touch_reset(void)
{
    struct s3908_event events[S3908_MAX_CONTACTS];
    if (!is_lemonades()) return;
    size_t count = 0;
    if (touch_transport.bus)
        s3908_transport_stop(&touch_transport, touch_bus.last_ms, events, &count);
    else
        s3908_session_stop(&touch_session, events, &count);
    post(events, count);
}

int lemonades_touch_start(uint64_t now_ms)
{
    struct s3908_event events[S3908_MAX_CONTACTS];
    size_t count = 0;
    if (!is_lemonades() || touch_transport.bus) return S3908_BAD_ARGUMENT;
    s3908_session_start(&touch_session, now_ms, events, &count);
    post(events, count);
    return S3908_OK;
}

int lemonades_touch_poll(uint64_t now_ms)
{
    struct s3908_event events[S3908_MAX_CONTACTS];
    size_t count = 0;
    if (!is_lemonades() || touch_transport.bus) return S3908_BAD_ARGUMENT;
    int status = s3908_session_poll(&touch_session, now_ms, events, &count);
    post(events, count);
    return status;
}

int lemonades_touch_write(uint64_t now_ms, size_t limit, unsigned char *out,
    size_t capacity, size_t *length)
{
    if (length) *length = 0;
    int status = lemonades_touch_poll(now_ms);
    if (status != S3908_OK) return status;
    return s3908_session_write(&touch_session, now_ms, limit, out, capacity, length);
}

int lemonades_touch_message(uint64_t now_ms, const unsigned char *frame, size_t size)
{
    struct s3908_event events[S3908_MAX_CONTACTS];
    size_t count = 0;
    if (!is_lemonades() || touch_transport.bus) return S3908_BAD_ARGUMENT;
    int status = s3908_session_message(&touch_session, now_ms, frame, size, events, &count);
    post(events, count);
    return status;
}

/* Caller has already provisioned and exclusively owns the resources. These
 * callbacks access the mapped SE13 registers; this function never maps an address
 * or enables a clock. Wrong-board calls are rejected BEFORE any MMIO callback. */
int lemonades_touch_bus_bind(const struct s3908_geni_io *io, uint64_t now_ms)
{
    struct s3908_event events[S3908_MAX_CONTACTS];
    struct s3908_geni candidate = {0};
    size_t count = 0;
    if (!is_lemonades() || touch_transport.running) return S3908_BAD_ARGUMENT;
    int status = s3908_geni_bind(&candidate, io);
    if (status != 0) return status;
    touch_bus = candidate;
    status = s3908_transport_start(&touch_transport, &touch_bus, &touch_session, now_ms, events, &count);
    post(events, count);
    return status;
}

int lemonades_touch_bus_poll(uint64_t now_ms, int attention)
{
    struct s3908_event events[S3908_MAX_CONTACTS];
    size_t count = 0;
    if (!is_lemonades() || !touch_transport.bus) return S3908_BAD_ARGUMENT;
    int status = s3908_transport_poll(&touch_transport, now_ms, attention, events, &count);
    post(events, count);
    return status;
}

int lemonades_touch_bus_stop(uint64_t now_ms)
{
    struct s3908_event events[S3908_MAX_CONTACTS];
    size_t count = 0;
    if (!is_lemonades() || !touch_transport.bus) return S3908_BAD_ARGUMENT;
    int status = s3908_transport_stop(&touch_transport, now_ms, events, &count);
    post(events, count);
    return status;
}

int lemonades_touch_bus_quiesced(void)
{
    if (!is_lemonades() || !touch_transport.bus) return S3908_BAD_ARGUMENT;
    if (touch_transport.running) return 0;
    return touch_bus.phase == SG_IDLE ||
        (touch_bus.phase == SG_FAILED && touch_bus.recovery > 0);
}

int lemonades_touch_bus_unbind(void)
{
    if (lemonades_touch_bus_quiesced() != 1) return S3908_GENI_UNPREPARED;
    /* No register access after clearing the last copies of the callbacks. */
    touch_transport = (struct s3908_transport){0};
    touch_bus = (struct s3908_geni){0};
    return 0;
}
