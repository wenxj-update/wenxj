// 可选:编译一个小 dll 用于验证 DllLoader 加载链路(不参与主链路 MVP)。
// 编译(clang/msvc): clang -shared -o mock_algo.dll gen_mock_dll.c
// 然后在 signature.py 注册 FuncSignature(name="mock_add", argtypes=(c_int,c_int), restype=c_int)
#include <stdint.h>

__declspec(dllexport) int32_t mock_add(int32_t a, int32_t b) {
    return a + b;
}

__declspec(dllexport) int32_t ComputeVisibility(const void* targets, int32_t n_targets,
                                                 const double* orbit, int32_t n_orbit,
                                                 void* results, int32_t* n_results) {
    // 占位:真实可见性计算待 C 端实现
    *n_results = 0;
    return 0;
}
