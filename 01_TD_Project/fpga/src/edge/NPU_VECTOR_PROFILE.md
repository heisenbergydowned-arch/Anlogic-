# NPU 39维向量分类配置

用户已确认最终用途为39维向量分类，不使用YOLO检测头或图像Resize。本轮关闭这两个公开可选模块，保留Whole NN以及POOLING/ACTIVATE/UPSAMPLE/ROUTE/SHORTCUT，未修改厂商加密实现、端口、PS原生时钟或独立HDMI显示链。

变更同步到 `design_0/Design.xml`、IP内的`Design.xml`、`.params_design_0_Video_NPU_0.txt`及`RTL/include/define.v`。`SOFT_RESIZE=0`、`SOFT_YOLO=0`、`PRE_PROCESS=0`；`SOFT_NN=1`、`ALL_OPERATOR=1`及现有NN算子保持。Windows备份为`backups/vector_npu_20261009_r4`。重新配置IP时也必须保留这组选择，不能用出厂YOLO demo覆盖。

NPU仍位于原AXI地址空间，普通NN寄存器地址未重排。原元数据中的YOLO (`0x91002000`) 和Resize (`0x91003000`) 地址洞不代表模块存在：PS不得执行YOLO后处理或图像Resize请求，也不得轮询它们等待完成。不能从“保留相同端口与地址”推断旧demo初始化代码完全兼容；需Linux组核对实际驱动初始化访问。

当前本地MLP导出脚本使用Gemm/Relu/Softmax，模型元数据为39输入/5分类。板上Alnpu是否支持最终量化模型的FC/Gemm、Softmax、张量形状与量化格式仍需真实加载、执行、与PC参考对拍。仅编译通过不代表NPU推理通过；保持现有Alnpu-only失败语义，不偷偷回退CPU后宣称NPU成功。

FCB1/FRM1/WAV1的GP0页面、39维顺序、quality/版本号、硬保护与执行权限均未改变。模型异常/无响应时，FPGA继续独立监测与保护；模型不能直接接管风机供电。TEST仍强制PWM/供电为低。

新完整TEST/REAL必须使用全新输出目录。只有对应源码哈希的资源、布局布线、Setup/Hold/Period、STA覆盖及实际PS时钟门禁全部通过，才能发布位流。无验收位流不得更新SD卡。板上HDMI、NPU、传感器和外部执行器需要分别验收。
