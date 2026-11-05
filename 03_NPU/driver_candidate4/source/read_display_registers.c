/* Read only the display registers documented in the checked vendor sources.
 * Use volatile 32-bit loads: device MMIO must not be read via memcpy/SIMD.
 */
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/mman.h>
#include <sys/ioctl.h>
#include <unistd.h>
#include <linux/fb.h>

int main(void) {
    const unsigned offsets[]={0,4,0x18,0x24,0x28,0x50,0x54,0x58,0x5c,0x60,0x64,0x68};
    int fd=open("/dev/mem",O_RDONLY|O_SYNC);
    if(fd<0){perror("open mem");return 1;}
    volatile uint32_t *dma=mmap(0,4096,PROT_READ,MAP_SHARED,fd,0x80200000);
    volatile uint32_t *vtc=mmap(0,4096,PROT_READ,MAP_SHARED,fd,0x80100000);
    volatile uint32_t *clk=mmap(0,4096,PROT_READ,MAP_SHARED,fd,0x80101000);
    if(dma==MAP_FAILED||vtc==MAP_FAILED||clk==MAP_FAILED){perror("mmap");return 1;}
    printf("{\"dma\":{");
    for(unsigned i=0;i<sizeof offsets/sizeof offsets[0];i++)
        printf("%s\"0x%02x\":%u",i?",":"",offsets[i],dma[offsets[i]/4]);
    printf("},\"vtc\":[");
    for(unsigned i=0;i<9;i++)printf("%s%u",i?",":"",vtc[i]);
    printf("],\"clock_status\":%u,\"clock_output_enable\":%u",clk[2],clk[3]);
    munmap((void*)dma,4096);munmap((void*)vtc,4096);munmap((void*)clk,4096);close(fd);
    struct fb_fix_screeninfo fix; fd=open("/dev/fb0",O_RDONLY);
    if(fd<0||ioctl(fd,FBIOGET_FSCREENINFO,&fix)){perror("fb ioctl");return 1;}
    printf(",\"fb_phys\":%lu,\"fb_bytes\":%u,\"stride\":%u,\"mmio_writes\":0}\n",fix.smem_start,fix.smem_len,fix.line_length);
    close(fd);return 0;
}
