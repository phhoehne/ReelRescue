#include <stdint.h>
#include <stddef.h>
static uint32_t t[256];
void init(void){for(unsigned i=0;i<256;i++){uint32_t x=i;for(int j=0;j<8;j++)x=(x>>1)^((x&1)?0xd8018001:0);t[i]=x;}}
uint32_t edc(const unsigned char *p,size_t n){uint32_t c=0;while(n--)c=(c>>8)^t[(c^*p++)&255];return c;}
