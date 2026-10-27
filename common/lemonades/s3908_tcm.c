/* Independent implementation of the framing contract reviewed in
 * syna_tcm_read_message / syna_tcm_continued_read (see LEMONADES-S3908.md).
 */
#include "s3908_tcm.h"

void s3908_tcm_reset(struct s3908_tcm *s)
{
    if (s) *s = (struct s3908_tcm){0};
}

static int failed(struct s3908_tcm *s)
{
    s3908_tcm_reset(s);
    return S3908_BAD_FRAME;
}

static int finish(struct s3908_tcm *s)
{
    /* Linux omits a final read when only the padding byte is left. Retain
     * evidence of that behavior; synthesized padding is not a captured byte. */
    if (s->total - s->used == 1) {
        s->frame[s->used++] = 0x5a;
        s->synthesized_padding = 1;
    }
    if (s->used < s->total) return S3908_TCM_MORE;
    if (s->frame[s->total - 1] != 0x5a) return failed(s);
    s->ready = 1;
    return S3908_OK;
}

static int begin(struct s3908_tcm *s, const uint8_t *chunk, size_t length, int normal)
{
    size_t total;
    if (!s || !chunk) return S3908_BAD_ARGUMENT;
    /* Dropping an unfinished read requires an explicit reset/resync. */
    if (s->used && !s->ready) return failed(s);
    s3908_tcm_reset(s);
    if (length < 4 || chunk[0] != 0xa5 || chunk[1] == 3 || chunk[1] == 0xff ||
        (normal && chunk[1] != 0x11)) return failed(s);
    if (!normal && (chunk[1] == 0 || chunk[1] == 2)) {
        s->frame[0] = 0xa5;
        s->frame[1] = chunk[1];
        s->frame[4] = 0x5a;
        s->used = s->total = 5;
        s->ready = s->synthesized_padding = 1;
        return S3908_OK;
    }
    total = 5u + chunk[2] + ((size_t)chunk[3] << 8);
    if (total > sizeof(s->frame) || (normal && (total < 6 || total > S3908_MAX_FRAME_SIZE)))
        return failed(s);
    s->total = total;
    s->used = length < total ? length : total;
    for (size_t i = 0; i < s->used; ++i) s->frame[i] = chunk[i];
    return finish(s);
}

int s3908_tcm_begin(struct s3908_tcm *s, const uint8_t *chunk, size_t length)
{
    return begin(s, chunk, length, 1);
}

int s3908_tcm_begin_message(struct s3908_tcm *s, const uint8_t *chunk, size_t length)
{
    return begin(s, chunk, length, 0);
}

size_t s3908_tcm_next_read(const struct s3908_tcm *s, size_t chunk_limit)
{
    if (!s || s->ready || !s->total || s->used >= s->total || chunk_limit < 4) return 0;
    size_t remaining = s->total - s->used;
    return (remaining < chunk_limit - 2 ? remaining : chunk_limit - 2) + 2;
}

int s3908_tcm_continue(struct s3908_tcm *s, const uint8_t *chunk, size_t length)
{
    if (!s || !chunk) return S3908_BAD_ARGUMENT;
    if (s->ready || !s->total || s->used >= s->total || length <= 2 ||
        length - 2 > s->total - s->used || chunk[0] != 0xa5 || chunk[1] != 3) return failed(s);
    for (size_t i = 2; i < length; ++i) s->frame[s->used++] = chunk[i];
    return finish(s);
}
