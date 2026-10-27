#include <assert.h>
#include <string.h>
#include <pexpert/hackios_platform.h>

static const void *property;
static unsigned length;
static int lookup_ok = 1, property_ok = 1;
int SecureDTLookupEntry(const DTEntry from, const char *path, DTEntry *out)
{
    assert(!from && !strcmp(path, "/chosen"));
    *out = (DTEntry)1;
    return lookup_ok ? kSuccess : -1;
}
int SecureDTGetProperty(const DTEntry entry, const char *name, const void **out, unsigned *size)
{
    assert(entry == (DTEntry)1 && !strcmp(name, "hackios,board"));
    *out = property;
    *size = length;
    return property_ok ? kSuccess : -1;
}
int main(void)
{
    const char *names[] = {"redwood", "lemonades", "qemu-virt", "", "redwood-extra", "REDWOOD"};
    for (unsigned i = 0; i < sizeof(names) / sizeof(names[0]); ++i) {
        property = names[i];
        length = (unsigned)strlen(names[i]) + 1;
        assert(hackios_platform_allows(HACKIOS_CAP_REDWOOD_HW) == (i == 0));
        assert(hackios_platform_allows(HACKIOS_CAP_VIRTIO_MMIO) == (i == 2));
        assert(!hackios_platform_allows(0));
        assert(!hackios_platform_allows(3));
        assert(!hackios_platform_allows(4));
        --length; /* unterminated */
        assert(!hackios_platform_allows(1) && !hackios_platform_allows(2));
    }
    char short_buffer[] = {'r'};
    property = short_buffer; length = 1;
    assert(!hackios_platform_allows(1));
    property = "redwood\0junk"; length = sizeof("redwood\0junk");
    assert(!hackios_platform_allows(1));
    property = NULL; length = 8;
    assert(!hackios_platform_allows(1));
    property = "redwood"; length = 8;
    lookup_ok = 0; assert(!hackios_platform_allows(1));
    lookup_ok = 1; property_ok = 0; assert(!hackios_platform_allows(1));
    return 0;
}
