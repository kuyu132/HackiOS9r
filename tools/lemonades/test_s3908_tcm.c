#include "s3908_tcm.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

int main(void)
{
    const uint8_t frame[] = {0xa5,0x11,13,0,0, 0x13,10,0,20,0,0,0,0,0,0,0,0, 0x5a};
    struct s3908_tcm s = {0};
    struct s3908_report report;
    uint8_t chunk[32] = {0xa5,3};
    for (size_t first = 4; first <= sizeof(frame); ++first) {
        for (size_t limit = 4; limit <= 24; ++limit) {
            s3908_tcm_reset(&s);
            int result = s3908_tcm_begin(&s, frame, first);
            while (result == S3908_TCM_MORE) {
                size_t next = s3908_tcm_next_read(&s, limit);
                assert(next >= 4 && next <= limit);
                memcpy(chunk + 2, frame + s.used, next - 2);
                result = s3908_tcm_continue(&s, chunk, next);
            }
            assert(result == 0 && s.ready && s.used == sizeof(frame));
            assert(!memcmp(s.frame, frame, sizeof(frame)));
            assert(s3908_decode_normal(s3908_normal_config, 19, s.frame, s.total, &report) == 0);
            assert(report.active_mask == 8);
            assert(s3908_tcm_next_read(&s, limit) == 0);
        }
    }
    uint8_t predictive[32];
    memcpy(predictive, frame, sizeof(frame));
    memset(predictive + sizeof(frame), 0xee, sizeof(predictive) - sizeof(frame));
    assert(s3908_tcm_begin(&s, predictive, sizeof(predictive)) == 0);
    assert(s.used == sizeof(frame) && !s.synthesized_padding);
    assert(s3908_tcm_begin(&s, frame, sizeof(frame) - 1) == 0 && s.synthesized_padding);
    predictive[sizeof(frame) - 1] = 0;
    assert(s3908_tcm_begin(&s, predictive, sizeof(frame)) < 0 && !s.ready && !s.total);
    assert(s3908_tcm_continue(&s, chunk, 4) < 0);
    assert(s3908_tcm_begin(&s, frame, 4) == S3908_TCM_MORE);
    assert(s3908_tcm_begin(&s, frame, 4) < 0 && !s.total);
    assert(s3908_tcm_begin(&s, frame, 4) == S3908_TCM_MORE);
    chunk[1] = 0x11;
    assert(s3908_tcm_continue(&s, chunk, 4) < 0 && !s.total);
    assert(s3908_tcm_begin(&s, frame, 4) == S3908_TCM_MORE);
    chunk[1] = 3;
    assert(s3908_tcm_continue(&s, chunk, sizeof(chunk)) < 0 && !s.total);
    for (unsigned byte = 0; byte < 256; ++byte) {
        uint8_t bad[] = {0xa5,0x11,0xff,(uint8_t)byte};
        assert(s3908_tcm_begin(&s, bad, sizeof(bad)) < 0 && !s.ready);
    }
    puts("S3908 continued-read splits, predictive tail, padding provenance and resync: PASS");
}
