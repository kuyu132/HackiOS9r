/* Independent implementation of the normal report format documented in
 * LineageOS's Syna_tcm_oncell driver. See docs/LEMONADES-S3908.md for exact revision.
 */
#include "s3908_report.h"

const uint8_t s3908_normal_config[S3908_NORMAL_CONFIG_SIZE] = {
    16, 8,       /* gesture: 8 bits */
    1,           /* foreach active object */
    6, 4, 7, 4,  /* ID, classification: 4 bits each */
    8, 16, 9, 16,/* X, Y: 16 bits each */
    11, 12, 12, 12, /* X/Y widths: 12 bits each */
    203, 32,     /* customer grip info: 32 bits */
    3, 0         /* foreach end, end */
};

static uint16_t le16(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}

int s3908_decode_normal(const uint8_t *config, size_t config_size,
                       const uint8_t *frame, size_t frame_size,
                       struct s3908_report *out)
{
    struct s3908_report report = {0};
    size_t payload_size, count, i;
    if (!config || !frame || !out)
        return S3908_BAD_ARGUMENT;
    if (config_size < S3908_NORMAL_CONFIG_SIZE || config_size > S3908_MAX_CONFIG_SIZE)
        return S3908_UNSUPPORTED_CONFIG;
    for (i = 0; i < config_size; ++i) {
        uint8_t expected = i < S3908_NORMAL_CONFIG_SIZE ? s3908_normal_config[i] : 0;
        if (config[i] != expected)
            return S3908_UNSUPPORTED_CONFIG;
    }
    if (frame_size < 6 || frame_size > S3908_MAX_FRAME_SIZE)
        return S3908_BAD_FRAME;
    if (frame[0] != 0xa5 || frame[1] != 0x11)
        return S3908_BAD_FRAME;
    payload_size = le16(frame + 2);
    if (payload_size + 5 != frame_size || payload_size < 1 ||
        (payload_size - 1) % 12 || frame[frame_size - 1] != 0x5a)
        return S3908_BAD_FRAME;
    count = (payload_size - 1) / 12;
    report.gesture = frame[4];
    report.object_count = (uint8_t)count;
    for (i = 0; i < count; ++i) {
        const uint8_t *p = frame + 5 + i * 12;
        unsigned id = p[0] & 15, classification = p[0] >> 4;
        struct s3908_contact *contact;
        uint16_t bit;
        if (id >= S3908_MAX_CONTACTS || classification > 2)
            return S3908_BAD_CONTACT;
        bit = (uint16_t)(1u << id);
        if (report.present_mask & bit)
            return S3908_BAD_CONTACT;
        report.present_mask |= bit;
        if (classification)
            report.active_mask |= bit;
        contact = &report.contacts[id];
        contact->classification = (uint8_t)classification;
        contact->x = le16(p + 1);
        contact->y = le16(p + 3);
        contact->width_x = (uint16_t)(p[5] | ((p[6] & 15u) << 8));
        contact->width_y = (uint16_t)((p[6] >> 4) | ((uint16_t)p[7] << 4));
        contact->edge_width_y = p[8];
        contact->edge_width_x = p[9];
        contact->edge_ratio_y = p[10];
        contact->edge_ratio_x = p[11];
    }
    *out = report;
    return S3908_OK;
}
