/*
 * Read a whole frame back in Ryubing, which returns only width/4 pixels of each row on readback.
 *
 * Seen in two ports with Ryubing 1.3.3 (OpenGL backend): glReadPixels of a w x h framebuffer filled only the first
 * w/4 pixels of each row, and captures of a 1280-wide frame had picture up to column 319. Workaround: blit the frame
 * into the left quarter of a target four times as wide, read that whole target, and keep the first w pixels of each
 * row. On the console the result is the same as a direct read, so keep it behind a switch and off by default.
 *
 * read_frame(fbo, w, h, dst, wide): dst gets w*h*4 bytes of RGBA, bottom row first (GL order).
 * Needs GL 3.0+ (framebuffer blit). One static target is reused while the size stays the same.
 */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <glad/glad.h>   /* or the GL loader the port uses */

void read_frame(GLuint fbo, uint32_t w, uint32_t h, uint8_t *dst, int wide)
{
    if (!wide) {
        glBindFramebuffer(GL_READ_FRAMEBUFFER, fbo);
        glPixelStorei(GL_PACK_ALIGNMENT, 1);
        glReadPixels(0, 0, (GLsizei)w, (GLsizei)h, GL_RGBA, GL_UNSIGNED_BYTE, dst);
        return;
    }
    static GLuint wfbo, wtex;
    static uint32_t ww, wh;
    static uint8_t *row_buf;
    if (ww != 4 * w || wh != h) {
        if (!wfbo) {
            glGenFramebuffers(1, &wfbo);
            glGenTextures(1, &wtex);
        }
        ww = 4 * w;
        wh = h;
        glBindTexture(GL_TEXTURE_2D, wtex);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, (GLsizei)ww, (GLsizei)wh, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
        glBindFramebuffer(GL_FRAMEBUFFER, wfbo);
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, wtex, 0);
        free(row_buf);
        row_buf = malloc((size_t)ww * wh * 4);
    }
    glBindFramebuffer(GL_READ_FRAMEBUFFER, fbo);
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, wfbo);
    glBlitFramebuffer(0, 0, (GLint)w, (GLint)h, 0, 0, (GLint)w, (GLint)h, GL_COLOR_BUFFER_BIT, GL_NEAREST);
    glBindFramebuffer(GL_READ_FRAMEBUFFER, wfbo);
    glPixelStorei(GL_PACK_ALIGNMENT, 1);
    glReadPixels(0, 0, (GLsizei)ww, (GLsizei)wh, GL_RGBA, GL_UNSIGNED_BYTE, row_buf);
    for (uint32_t y = 0; y < h; y++)   /* keep the left quarter of each wide row */
        memcpy(dst + (size_t)y * w * 4, row_buf + (size_t)y * ww * 4, (size_t)w * 4);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
}
