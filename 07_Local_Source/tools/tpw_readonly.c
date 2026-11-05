#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#include <stdio.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <time.h>
/* Passive, aligned 32-bit reads of TPW1 status only. No FIFO, ACK or write. */
int main(void) {
 int fd=open("/dev/mem",O_RDONLY|O_SYNC);
 if(fd<0){perror("open");return 2;}
 void *map=mmap(NULL,65536,PROT_READ,MAP_SHARED,fd,0x80400000);
 if(map==MAP_FAILED){perror("mmap");close(fd);return 2;}
 volatile const uint32_t *p=map;struct timespec start,now,delay={0,50000000};
 clock_gettime(CLOCK_MONOTONIC,&start);int result=0;
 for(unsigned i=0;i<61;i++){
  __sync_synchronize();uint32_t flags=p[0xa08/4],pair=p[0xa28/4];__sync_synchronize();
  clock_gettime(CLOCK_MONOTONIC,&now);
  double elapsed=(now.tv_sec-start.tv_sec)+(now.tv_nsec-start.tv_nsec)/1e9;
  printf("{\"elapsed\":%.6f,\"flags\":%u,\"target\":%u,\"duty\":%u}\n",elapsed,flags,pair>>16,pair&65535);fflush(stdout);
  if(!(flags&1)||(flags&2)||!(pair&65535)||(pair&65535)>4000)result=1;
  if(i<60)nanosleep(&delay,NULL);
 }
 munmap(map,65536);close(fd);return result;
}
