/* Original Foundation/CoreFoundation with a deterministic date, no host services. */
#import <Foundation/Foundation.h>
#include <stdio.h>
int main(void)
{
    @autoreleasepool {
        puts("LOCALE BEGIN date-formatter");fflush(stdout);
        CFLocaleRef locale=CFLocaleCreate(NULL,CFSTR("en_US_POSIX"));
        CFDateFormatterRef cf=locale?CFDateFormatterCreate(NULL,locale,kCFDateFormatterMediumStyle,kCFDateFormatterMediumStyle):NULL;
        if(locale)CFRelease(locale);
        printf("LOCALE CFDateFormatterCreate nonnull=%d\n",cf!=NULL);fflush(stdout);
        if(!cf){puts("LOCALE FAIL CF formatter unavailable");return 1;}
        CFRelease(cf);
        NSISO8601DateFormatter *iso=[[NSISO8601DateFormatter alloc] init];
        iso.timeZone=[NSTimeZone timeZoneForSecondsFromGMT:0];
        NSString *text=[iso stringFromDate:[NSDate dateWithTimeIntervalSinceReferenceDate:0]];
        printf("LOCALE ISO8601 value=%s\n",text?text.UTF8String:"(null)");fflush(stdout);
        if(![text isEqualToString:@"2001-01-01T00:00:00Z"]){puts("LOCALE FAIL ISO8601 value");return 1;}
        puts("LOCALE PASS iso8601");fflush(stdout);return 0;
    }
}
