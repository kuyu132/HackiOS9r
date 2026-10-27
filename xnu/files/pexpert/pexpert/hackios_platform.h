/* Hardware identity is independent of the iPhone identity used by user space.
 * Only a complete, NUL-terminated loader property grants hardware access.
 * Missing properties on older loaders deliberately grant no capabilities.
 */
#ifndef HACKIOS_PLATFORM_H
#define HACKIOS_PLATFORM_H
#include <stddef.h>

enum hackios_board {
	HACKIOS_UNKNOWN, HACKIOS_REDWOOD, HACKIOS_LEMONADES, HACKIOS_QEMU_VIRT
};
enum hackios_capability {
	HACKIOS_CAP_REDWOOD_HW = 1u, HACKIOS_CAP_VIRTIO_MMIO = 2u
};

static inline int
hackios_property_equals(const void *property, size_t size, const char *expected, size_t expected_size)
{
	const unsigned char *p = property;
	if (!p || size != expected_size) return 0;
	for (size_t i = 0; i < size; ++i) {
		if (p[i] != (unsigned char)expected[i]) return 0;
	}
	return 1;
}

static inline enum hackios_board
hackios_decode_board(const void *property, size_t size)
{
	if (hackios_property_equals(property, size, "redwood", sizeof("redwood"))) return HACKIOS_REDWOOD;
	if (hackios_property_equals(property, size, "lemonades", sizeof("lemonades"))) return HACKIOS_LEMONADES;
	if (hackios_property_equals(property, size, "qemu-virt", sizeof("qemu-virt"))) return HACKIOS_QEMU_VIRT;
	return HACKIOS_UNKNOWN;
}

static inline int
hackios_board_allows(enum hackios_board board, unsigned capability)
{
	unsigned allowed = board == HACKIOS_REDWOOD ? HACKIOS_CAP_REDWOOD_HW :
	    board == HACKIOS_QEMU_VIRT ? HACKIOS_CAP_VIRTIO_MMIO : 0;
	return capability != 0 && (allowed & capability) == capability;
}

#ifdef KERNEL
#include <pexpert/device_tree.h>
static inline int
hackios_platform_allows(unsigned capability)
{
	DTEntry chosen;
	void const *value = NULL;
	unsigned int size = 0;
	if (SecureDTLookupEntry(NULL, "/chosen", &chosen) != kSuccess ||
	    SecureDTGetProperty(chosen, "hackios,board", &value, &size) != kSuccess) return 0;
	return hackios_board_allows(hackios_decode_board(value, size), capability);
}
#endif
#endif
