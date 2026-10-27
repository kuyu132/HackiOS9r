#include "hid_client_abi.h"
uint64_t lemonades_hid_service_id(Service service)
{
    CFNumberRef number=IOHIDServiceClientGetRegistryID(service);
    int64_t value=0;
    if(!number || CFGetTypeID(number)!=CFNumberGetTypeID() ||
       !CFNumberGetValue(number,kCFNumberSInt64Type,&value))return 0;
    return (uint64_t)value;
}
CFDictionaryRef lemonades_hid_properties(CFStringRef product,unsigned built_in)
{
    if(built_in>1)return NULL;
    CFMutableDictionaryRef d=CFDictionaryCreateMutable(NULL,0,&kCFTypeDictionaryKeyCallBacks,&kCFTypeDictionaryValueCallBacks);
    int page=13,usage=4;
    CFNumberRef p=CFNumberCreate(NULL,kCFNumberIntType,&page),u=CFNumberCreate(NULL,kCFNumberIntType,&usage);
    const void *keys[]={CFSTR("DeviceUsagePage"),CFSTR("DeviceUsage")};
    const void *values[]={p,u};
    CFDictionaryRef pair=NULL;CFArrayRef pairs=NULL;
    if(!d || !p || !u)goto fail;
    pair=CFDictionaryCreate(NULL,keys,values,2,&kCFTypeDictionaryKeyCallBacks,&kCFTypeDictionaryValueCallBacks);
    if(!pair)goto fail;
    pairs=CFArrayCreate(NULL,(const void **)&pair,1,&kCFTypeArrayCallBacks);
    if(!pairs)goto fail;
    CFDictionarySetValue(d,CFSTR("PrimaryUsagePage"),p);CFDictionarySetValue(d,CFSTR("PrimaryUsage"),u);
    CFDictionarySetValue(d,keys[0],p);CFDictionarySetValue(d,keys[1],u);
    CFDictionarySetValue(d,CFSTR("DeviceUsagePairs"),pairs);
    CFDictionarySetValue(d,CFSTR("Product"),product);
    CFDictionarySetValue(d,CFSTR("Manufacturer"),CFSTR("HackiOS9r offline test"));
    CFDictionarySetValue(d,CFSTR("Transport"),CFSTR("Virtual"));
    CFDictionarySetValue(d,CFSTR("Built-In"),built_in?kCFBooleanTrue:kCFBooleanFalse);
    CFDictionarySetValue(d,CFSTR("DisplayIntegrated"),kCFBooleanTrue);
    CFRelease(pairs);CFRelease(pair);CFRelease(p);CFRelease(u);return d;
fail:
    if(pairs)CFRelease(pairs);if(pair)CFRelease(pair);if(p)CFRelease(p);if(u)CFRelease(u);if(d)CFRelease(d);return NULL;
}
