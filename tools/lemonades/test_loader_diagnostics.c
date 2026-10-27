#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "diagnostics.h"

/* The test builder inserts the production compose_logs/stage_idle_logs here. */
/* PRODUCTION_LOG_COMPOSITION */

static char pattern(size_t i) { return (char)(i * 37u % 251u); }

int main(void)
{
	struct loader_log_buffer log = {0};
	char dst[LOADER_LOG_EXPORT_MAX + 2];
	size_t boundaries[] = {0, 1, LOADER_LOG_HEAD - 1, LOADER_LOG_HEAD,
	    LOADER_LOG_HEAD + 1, LOADER_LOG_HEAD + LOADER_LOG_TAIL - 1,
	    LOADER_LOG_HEAD + LOADER_LOG_TAIL, LOADER_LOG_HEAD + LOADER_LOG_TAIL + 1,
	    LOADER_LOG_HEAD + LOADER_LOG_TAIL * 4 + 913};
	for (unsigned t = 0; t < sizeof(boundaries)/sizeof(boundaries[0]); t++) {
		loader_log_reset(&log);
		size_t count = boundaries[t];
		for (size_t i = 0; i < count; i++) loader_log_put(&log, pattern(i));
		memset(dst, 0x7f, sizeof(dst));
		assert(loader_log_copy(&log, dst + 1, LOADER_LOG_EXPORT_MAX - 1) == 0);
		assert((unsigned char)dst[1] == 0x7f);
		size_t n = loader_log_copy(&log, dst + 1, LOADER_LOG_EXPORT_MAX);
		assert((unsigned char)dst[0] == 0x7f && (unsigned char)dst[n + 1] == 0x7f);
		size_t head = count < LOADER_LOG_HEAD ? count : LOADER_LOG_HEAD;
		size_t tail = count - head < LOADER_LOG_TAIL ? count - head : LOADER_LOG_TAIL;
		size_t lost = count - head - tail;
		assert(log.dropped == lost);
		assert(n == head + tail + (lost ? sizeof(loader_log_gap) - 1 : 0));
		for (size_t i = 0; i < head; i++) assert(dst[1 + i] == pattern(i));
		if (lost) assert(!memcmp(dst + 1 + head, loader_log_gap, sizeof(loader_log_gap) - 1));
		for (size_t i = 0; i < tail; i++) assert(dst[1 + n - tail + i] == pattern(count - tail + i));
		char again[LOADER_LOG_EXPORT_MAX];
		assert(loader_log_copy(&log, again, sizeof(again)) == n);
		assert(!memcmp(dst + 1, again, n));
	}
	log.dropped = UINT64_MAX;
	loader_log_put(&log, 'z');
	assert(log.dropped == UINT64_MAX);
	char text[64];
	loader_format(text, sizeof(text), "%s %d %x %%", "returned", UINT64_MAX, UINT64_MAX);
	assert(!strcmp(text, "returned 18446744073709551615 ffffffffffffffff %"));
	loader_format(text, 5, "%s", "abcdef");
	assert(!strcmp(text, "abcd"));
	loader_format(text, 1, "%d", (uint64_t)123);
	assert(text[0] == 0);
	text[0] = 'x'; loader_format(text, 0, "%s", "abc"); assert(text[0] == 'x');
	loader_format(NULL, 0, "%d", (uint64_t)0);
	loader_format(text, sizeof(text), "%d %d %d", (uint64_t)1080, (uint64_t)2400, (uint64_t)4320);
	assert(!strcmp(text, "1080 2400 4320"));

	/* Exercise the actual loader composition and repeated idle USB export. */
	for (unsigned i = 0; i < 100000; i++) loader_log_put(&loader_log, 'L');
	const char panic[] = "panic: fault\0binary registers\xff";
	compose_logs(panic, sizeof(panic));
	assert(completed_log_len == staged_len);
	uint64_t saved_len = staged_len;
	static char saved[sizeof(out_buf)];
	memcpy(saved, out_buf, sizeof(saved));
	assert(!memcmp(out_buf + LOADER_LOG_EXPORT_MAX + strlen("\n== KERNEL LOG ==\n"), panic, sizeof(panic)));
	for (unsigned i = 0; i < 3; i++) {
		staged_data = "screenshot"; staged_len = 10;
		stage_idle_logs();
		assert(staged_data == out_buf && staged_len == saved_len);
		assert(!memcmp(saved, out_buf, sizeof(saved)));
	}
	static char oversized[sizeof(out_buf) + 100];
	memset(oversized, 'K', sizeof(oversized));
	compose_logs(oversized, sizeof(oversized));
	assert(staged_len < sizeof(out_buf));
	assert(!memcmp(out_buf + staged_len - strlen("\n== END OF LOG ==\n"), "\n== END OF LOG ==\n", strlen("\n== END OF LOG ==\n")));
	loader_log_reset(&loader_log); completed_log_len = 0;
	loader_log_put(&loader_log, 'N');
	stage_idle_logs(); assert(staged_len == 1 && out_buf[0] == 'N');
	puts("LOADER DIAGNOSTICS HOST PASS");
}
