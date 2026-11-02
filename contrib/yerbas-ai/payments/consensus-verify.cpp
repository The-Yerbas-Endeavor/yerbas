#include <iostream>
#include <string>
#include <vector>
#include "script/yerbasconsensus.h"
std::vector<unsigned char> decode(const std::string& s) {
 if(s.size()%2 || s.size()>2000) throw 1;
 std::vector<unsigned char> v;
 for(size_t i=0;i<s.size();i+=2){ auto a=s.substr(i,2); if(a.find_first_not_of("0123456789abcdef")!=std::string::npos)throw 1; v.push_back(std::stoul(a,nullptr,16)); } return v;
}
int main(int argc,char**argv){try{if(argc!=3)return 2;auto s=decode(argv[1]),t=decode(argv[2]);yerbasconsensus_error e;int r=yerbasconsensus_verify_script(s.data(),s.size(),t.data(),t.size(),0,yerbasconsensus_SCRIPT_FLAGS_VERIFY_ALL,&e);std::cout<<r<<" "<<e<<std::endl;return 0;}catch(...){return 2;}}
