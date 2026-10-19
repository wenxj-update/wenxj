
import tkinter as tk
from tkinter import ttk , filedialog
import re
import math
import crcmod
from binascii import unhexlify
from datetime import datetime
import os
import sys
import json
labels = {
        0:"加热通道0锂电池1加热器3主份",
        1:"加热通道1锂电池1加热器5主份",
        2:"加热通道2锂电池2加热器1主份",
        3:"加热通道3锂电池2加热器5主份",
        4:"加热通道4锂电池1加热器1主份",
        5:"加热通道5锂电池1加热器2主份",
        6:"加热通道6锂电池1加热器4主份",
        7:"加热通道7锂电池1加热器6备份",
        8:"加热通道8锂电池1加热器7",
        9:"加热通道9锂电池1加热器8",
        10:"加热通道10锂电池2加热器2主份",
        11:"加热通道11锂电池2加热器3主份",
        12:"加热通道12锂电池2加热器4主份",
        13:"加热通道13锂电池2加热器6备份",
        14:"加热通道14锂电池2加热器7",
        15:"加热通道15锂电池2加热器8",
        16:"加热通道16光纤陀螺A加热器",
        17:"加热通道17光纤陀螺B加热器",
        18:"加热通道18磁强计加热器",
        19:"加热通道19飞轮A加热器",
        20:"加热通道20飞轮B加热器",
        21:"加热通道21飞轮C加热器",
        22:"加热通道22飞轮D加热器",
        23:"加热通道23电源控制器加热器1",
        24:"加热通道24电源控制器加热器2",
        25:"加热通道25综合电子计算机加热器1",
        26:"加热通道26综合电子计算机加热器2",
        27:"加热通道27QV收发组件A加热器1",
        28:"加热通道28QV收发组件A加热器2",
        29:"加热通道29QV收发组件B加热器1",
        30:"加热通道30QV收发组件B加热器2",
        31:"加热通道31导航增强处理机加热器1",
        32:"加热通道32导航增强处理机加热器2",
        33:"加热通道33导航增强处理机加热器3",
        34:"加热通道34导航增强处理机加热器4",
        35:"加热通道35三通道固放加热器1主份",
        36:"加热通道36三通道固放加热器2主份",
        37:"加热通道37三通道固放加热器3主份",
        38:"加热通道38三通道固放加热器4备份",
        39:"加热通道39激光处理机B1加热器1",
        40:"加热通道40激光处理机B1加热器2",
        41:"加热通道41激光处理机B1加热器3",
        42:"加热通道42激光处理机B2加热器1",
        43:"加热通道43激光处理机B2加热器2",
        44:"加热通道44激光处理机B2加热器3",
        45:"加热通道45激光处理机舱板加热器1",
        46:"加热通道46激光处理机舱板加热器2",
        47:"加热通道47光纤放大器B1加热器1",
        48:"加热通道48光纤放大器B1加热器2",
        49:"加热通道49光纤放大器B1加热器3",
        50:"加热通道50备用",
        51:"加热通道51备用",
        52:"加热通道52备用",
        53:"加热通道53备用",
        54:"加热通道54备用",
        55:"加热通道55备用",
        56:"加热通道56备用",
        57:"加热通道57备用",
        58:"加热通道58光纤放大器B1加热器4",
        59:"加热通道59光纤放大器B1加热器5",
        60:"加热通道60光纤放大器B2加热器1",
        61:"加热通道61光纤放大器B2加热器2",
        62:"加热通道62光纤放大器B2加热器3",
        63:"加热通道63光纤放大器B2加热器4",
        64:"加热通道64光纤放大器B2加热器5",
        65:"加热通道65综合处理单机加热器1",
        66:"加热通道66综合处理单机加热器2",
        67:"加热通道67综合处理机加热器3",
        68:"加热通道68搭载激光处理机加热器",
        69:"加热通道69电源处理与控制单元加热器1主份",
        70:"加热通道70电源处理与控制单元加热器2备份",
        71:"加热通道71压力流量调节模块加热器1",
        72:"加热通道72压力流量调节模块加热器2",
        73:"加热通道73气瓶加热器1主份",
        74:"加热通道74气瓶加热器2备份",
        75:"加热通道75原子钟加热器1主份",
        76:"加热通道76原子钟加热器2主份",
        77:"加热通道77原子钟加热器3备份",
        78:"加热通道78多工器加热器1主份",
        79:"加热通道79多工器加热器2主份",
        80:"加热通道80多工器加热器3备份",
        81:"加热通道81原子钟安装板加热器1",
        82:"加热通道82原子钟安装板加热器2",
        83:"加热通道83原子钟安装板加热器3",
        84:"加热通道84原子钟安装板加热器4",
        85:"加热通道85多工器安装板加热器1",
        86:"加热通道86多工器安装板加热器2",
        87:"加热通道87多工器安装板加热器3",
        88:"加热通道88多工器安装板加热器4",
        89:"加热通道89星敏感器A加热器1主份",
        90:"加热通道90星敏感器A加热器2备份",
        91:"加热通道91星敏感器B加热器1主份",
        92:"加热通道92星敏感器B加热器2备份",
        93:"加热通道93星敏感器C加热器1主份",
        94:"加热通道94星敏感器C加热器2备份",
        95:"加热通道95SADA A轴加热器1",
        96:"加热通道96SADA A轴加热器2",
        97:"加热通道97信标载荷加热器",
        98:"加热通道98监视相机控制器加热器",
        99:"加热通道99监视相机1加热器",
        100:"加热通道100监视相机2加热器",
        101:"加热通道101角位移测量传感器主机加热器",
        102:"加热通道102角位移测量传感器1加热器",
        103:"加热通道103角位移测量传感器2加热器",
        104:"加热通道104KA发射天线A加热器",
        105:"加热通道105KA发射天线B加热器",
        106:"加热通道106KA接收天线A加热器",
        107:"加热通道107KA接收天线B加热器",
        108:"加热通道108备用",
        109:"加热通道109备用",
        110:"加热通道110备用",
        111:"加热通道111备用",
        112:"加热通道112备用",
        113:"加热通道113备用",
        114:"加热通道114备用",
        115:"加热通道115备用"

        }
# labels_entry={}
labels_entry={ 
    0:"15,17,0",
    1:"13,15,0",
    2:"15,17,0",
    3:"15,17,0",
    4:"15,17,0",
    5:"15,17,0",
    6:"15,17,0",
    7:"13,15,0",
    8:"13,15,0",
    9:"13,15,0",
    10:"15,17,0",
    11:"15,17,0",
    12:"15,17,0",
    13:"15,17,0",
    14:"13,15,0",
    15:"13,15,0",
    16:"-17,-15,0",
    17:"-17,-15,0",
    18:"-17,-15,0",
    19:"-8,-6,0",
    20:"-8,-6,0",
    21:"-8,-6,0",
    22:"-8,-6,0",
    23:"-13,-10,0",
    24:"-14,-12,0",
    25:"-17,-15,0",
    26:"-17,-15,0",
    27:"-27,-25,0",
    28:"-28,-26,0",
    29:"-27,-25,0",
    30:"-28,-26,0",
    31:"3.8, 4.2,0",
    32:"3.8, 4.2,0",
    33:"3.8, 4.2,0",
    34:"3.8, 4.2,0",
    35:"3.8, 4.2,0",
    36:"3.8, 4.2,0",
    37:"3.8, 4.2,0",
    38:"3.8, 4.2,0",
    39:"3,5,0",
    40:"3,5,0",
    41:"3,5,0",
    42:"3,5,0",
    43:"3,5,0",
    44:"3,5,0",
    45:"3,5,0",
    46:"3,5,0",
    47:"3,5,0",
    48:"3,5,0",
    49:"3,5,0",
    50:"3,5,0",
    51:"3,5,0",
    52:"3,5,0",
    53:"3,5,0",
    54:"3,5,0",
    55:"3,5,0",
    56:"3,5,0",
    57:"3,5,0",
    58:"3,5,0",
    59:"3,5,0",
    60:"3,5,0",
    61:"3,5,0",
    62:"3,5,0",
    63:"3,5,0",
    64:"3,5,0",
    65:"-17,-15,0",
    66:"-18,-16,0",
    67:"-18,-16,0",
    68:"-8,-6,0",
    69:"-13,-10,0",
    70:"-14,-12,0",
    71:"13,15,0",
    72:"12,14,0",
    73:"13,15,0",
    74:"12,14,0",
    75:"3.8, 4.2,0",
    76:"3.8, 4.2,0",
    77:"3.8, 4.2,0",
    78:"25.8,26.2,0",
    79:"25.8,26.2,0",
    80:"25.8,26.2,0",
    81:"19.8,20.2,0",
    82:"19.8,20.2,0",
    83:"19.8,20.2,0",
    84:"19.8,20.2,0",
    85:"20.8,21.2,0",
    86:"20.8,21.2,0",
    87:"20.8,21.2,0",
    88:"20.8,21.2,0",
    89:"17,20,0",
    90:"16,18,0",
    91:"17,20,0",
    92:"16,18,0",
    93:"17,20,0",
    94:"16,18,0",
    95:"-5,-0,0",
    96:"-5,-0,0",
    97:"-18,-15,0",
    98:"-13,-10,0",
    99:"-13,-10,0",
    100:"-13,-10,0",
    101:"-17,-15,0",
    102:"-17,-15,0",
    103:"-17,-15,0",
    104:"-24,-22,0",
    105:"-24,-22,0",
    106:"-24,-22,0",
    107:"-24,-22,0",
    108:"-13,-10,0",
    109:"-17,-15,0",
    110:"-17,-15,0",
    111:"-17,-15,0",
    112:"-24,-22,0",
    113:"-24,-22,0",
    114:"-24,-22,0",
    115:"-24,-22,0",

        }
string_vars = []
options_data={'a':-6.01188,'b':4622.53337,'c':-86421.72414} 
  
class DataManagementApp:
    def __init__(self, master):
        self.count=0
        self.master = master
        self.master.title("热控指令生成软件_版本1.1")
        self.master.geometry("1300x750")
        
        # 顶部面板 - 三个下拉框
        self.top_frame = ttk.LabelFrame(master, text="状态设置", padding=10)
        self.top_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # 下拉框1:数据类别
        ttk.Label(self.top_frame, text="工作模式:").grid(row=0, column=0, padx=5)
        self.category_combo = ttk.Combobox(self.top_frame, 
                                         values=list({"长期在轨模式":"00", "载荷工作模式":"01", "轨控模式":"02", "故障模式":"03","发射前模式":"04"}.keys()),
                                         state="readonly")
        self.category_combo.current(0)  # 设置默认选中第一项
        self.category_combo.grid(row=0, column=1, padx=5)
        
        # 下拉框2:时间范围
        ttk.Label(self.top_frame, text="热控组数:").grid(row=0, column=2, padx=5)
        self.time_combo = ttk.Combobox(self.top_frame, 
                                     values=["第一组", "第二组", "第三组", "第四组"],
                                     state="readonly")
        self.time_combo.current(0)
        self.time_combo.grid(row=0, column=3, padx=5)
        
        # 下拉框3:操作类型
        ttk.Label(self.top_frame, text="开闭环状态:").grid(row=0, column=4, padx=5)
        value={"闭环66":"66", "开环99":"99","单独控制AA":"AA"}
        self.action_combo = ttk.Combobox(self.top_frame, 
                                       values=list(value.keys()),
                                       state="readonly")
        # print(list(value.keys())[0])
        self.action_combo.current(0)
        self.action_combo.grid(row=0, column=5, padx=5)

        # 主内容区
        self.main_frame = ttk.Frame(master)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # 左侧面板 - 116个不同名称的Label和Entry
        self.left_frame = ttk.LabelFrame(self.main_frame, text="阈值设置区")
        self.left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.canvas = tk.Canvas(self.left_frame)
        self.scrollbarX = ttk.Scrollbar(self.left_frame, orient="horizontal", command=self.canvas.xview,style='Horizontal.TScrollbar')
        self.scrollbarY = ttk.Scrollbar(self.left_frame, orient="vertical", command=self.canvas.yview,style='Vertical.TScrollbar')
       
        self.form_frame = ttk.Frame(self.canvas,padding=(5,15))
        
        self.form_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.form_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbarY.set,xscrollcommand=self.scrollbarX.set)
        
        bottom_frame = ttk.Frame(self.canvas)
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        
        self.scrollbarX.pack(in_=bottom_frame ,fill=tk.X)
        self.scrollbarY.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.init_label()
        # self.create_form_fields()
        
        # 右侧面板 - 文本区
        self.right_frame = ttk.LabelFrame(self.main_frame, text="指令码字", width=350)
        self.right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, padx=5)
        
        self.text_area = tk.Text(self.right_frame, wrap=tk.WORD, font=('Consolas', 10))
        self.scroll_text = ttk.Scrollbar(self.right_frame, command=self.text_area.yview)
        self.text_area.configure(yscrollcommand=self.scroll_text.set)
        
        self.text_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scroll_text.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 底部面板 - 按钮
        self.bottom_frame = ttk.Frame(master)
        self.bottom_frame.pack(fill=tk.X, pady=10)
        
        self.save_btn = ttk.Button(self.bottom_frame, text="导入阈值", width=15,command=lambda: self.import_temp())
        self.save_btn.pack(side=tk.LEFT, padx=20)
        
        self.reset_btn = ttk.Button(self.bottom_frame, text="生成指令", width=15,command=lambda: self.zuzhen())
        self.reset_btn.pack(side=tk.RIGHT, padx=20)
        
        # 样式配置
        self.style = ttk.Style()
        self.style.configure("TLabel", padding=3, font=('Arial', 9))
        self.style.configure("TEntry", padding=3)
        self.style.configure("TLabelframe.Label", font=('Arial', 10, 'bold'))
    # def import_temp(self):
    #     global  labels_entry
    #     # temp_data = {}
    #     # global labels_entry
    #     # try:
    #     with open("xx.json", 'r', encoding='utf-8') as f_temp:
    #         labels_entry = json.load(f_temp)
    #         return labels_entry
    def init_label(self):
        # 写入默认值
        global labels, labels_entry, string_vars
        self.field_names=[labels[i] for i in range(116)]
        field_value=[labels_entry[i] for i in range(116)]
        string_vars = [tk.StringVar(value=field_value[i]) for i in range(116)]
        print(11,type(string_vars))
        for i in range(116):
            row = i // 3  # 每行3组
            col = i % 3
            
            ttk.Label(self.form_frame, text=f"{self.field_names[i]}:").grid(
                row=row, column=col*2, sticky=tk.E, padx=5, pady=2)
            # field_value=tk.StringVar(value=f"{field_value[i]}:")  
            entry=tk.Entry(self.form_frame, width=22,textvariable=string_vars[i])
            entry.grid(row=row, column=col*2+1, sticky=tk.W, padx=5, pady=2)
           
    def calc_tem(self,value_tem): 
            T_1=float(value_tem)+273.15
            tem_top=2*options_data['c']
            # print(list(options_data.keys())[2])
            logr=options_data['a']-((options_data['b']**2-(tem_top/T_1+options_data['b'])**2)/(4*options_data['c']))
            # try: 
            # print(f"lnR的值：{logr}")
            Vref = 4.856
            lastV1=((math.exp(logr)*Vref)/(math.exp(logr)+10000))*4096/Vref
            # print(f"R的值：{math.exp(logr)}")
            lastV1_hex=hex(round(lastV1))[2:].upper()
            if len(lastV1_hex)%2==1:
               return '0'+lastV1_hex
            elif  len(lastV1_hex)==2:
               return '00'+lastV1_hex 
            print("V1 的解为:", lastV1_hex) 
    def get_group_range(self):
        """获取当前选中的热控组数对应的通道范围"""
        group_mapping = {
            "第一组": (0, 28),    # 通道0-29
            "第二组": (29, 57),   # 通道30-50
            "第三组": (58, 86),   # 通道51-80
            "第四组": (87, 115)   # 通道81-115
        }
        selected_group = self.time_combo.get()
        return group_mapping.get(selected_group, (0, 115))  # 默认返回全部通道
    def get_work_model(self):
        mode_mapping = self.category_combo.get()
        mode_group = {"长期在轨模式":"00", "载荷工作模式":"01", "轨控模式":"02", 
                       "故障模式":"03", "发射前模式":"04"}
        return mode_group.get(mode_mapping,"00")
        # return mode_mapping.get(mode_mapping,"00")
    def get_offon_model(self):
        loop_group = {"闭环66":"66", "开环99":"99","单独控制AA":"AA"}
        loop_mapping = self.action_combo.get()
        return loop_group.get(loop_mapping,"66")
    def create_form_fields(self):
        # 获取标签值
        global string_vars
        # work = self.get_work_model()
        work1 = self.get_offon_model()
        start_idx, end_idx = self.get_group_range()
        end = ""
        for i in range(start_idx, end_idx+1):
            tem_index=''.join("{:02x}".format(i)).upper()
            current_value = string_vars[i].get().strip()  # 获取修改后的值
            # print(string_vars[i])
            upper_limit,Threshold_lower_limi,hot_onoff = current_value.split(',')  # 阈值上下限
            # print(f"Entry {i}: Upper={upper_limit}, Lower={Threshold_lower_limi}")
            self.calc_tem(upper_limit)
            self.calc_tem(Threshold_lower_limi)
            if work1.strip()=='AA':
                if hot_onoff.strip()=="1":
                    pinjie = tem_index+' '+ "99"+self.calc_tem(Threshold_lower_limi)+self.calc_tem(upper_limit)
                    end += pinjie
                elif hot_onoff.strip()=="0":
                     pinjie = tem_index+' '+ "66"+self.calc_tem(Threshold_lower_limi)+self.calc_tem(upper_limit)
                     end += pinjie
                else:
                    pinjie = tem_index+' '+ "66"+self.calc_tem(Threshold_lower_limi)+self.calc_tem(upper_limit)
                    end += pinjie
            else:
                 pinjie = tem_index+' '+ work1+self.calc_tem(Threshold_lower_limi)+self.calc_tem(upper_limit)
                 end += pinjie
        return end
    def crc16_500(self,read):
        crc16_ibm = crcmod.mkCrcFun(0x11021, rev=False, initCrc=0xFFFF, xorOut=0x0000)
        data = read.replace(" ", "")
        str_list = hex(crc16_ibm(unhexlify(data))).upper()
        if len(str_list) < 6:
            str_list = str_list[0:2] + '0' * (6 - len(str_list)) + str_list[2:]
        crc_data = "".join(str_list)
        print(crc_data)
        print('CRC16校验:',crc_data[2:4]+ ' ' +crc_data[4:] )
        crc_data_F=crc_data[2:4]+ ' ' +crc_data[4:] 
        return crc_data_F  # '0x' + crc_data[4:] + crc_data[2:4]  
 
    def getVerify(self, txt):
            """校验, 方法为包主导头+包数据域的逐字节累加和的低八位"""
            rst = 0
            buffer = ''
            for gvi in txt:
                if not buffer:
                    buffer = gvi
                else:
                    rst += int(buffer+gvi, 16)
                    buffer = ''
            rst = bin(rst)
            if len(rst) < 18:
                rst = '0b' + '{:0>16}'.format(rst[2:])
            else:
                rst = '0b' + rst[-16:]
            rst = bin(0xFFFF - int(rst, 2))
            rst= hex(int(rst, 2))[2:].upper()
            return rst
    def gettime(self):
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")#获取button的按键时间
        return timestamp
    def saveTemOnoff(self):
        start_idx, end_idx = self.get_group_range()
        return [string_vars[i].get().strip() 
            for i in range(start_idx, end_idx+1)]  # 列表推导式:ml-citation{ref="2,6" data="citationList"}
    def list_count(self):#输出txt每条记录计数
        self.count+=1
        return self.count
    def zuzhen(self):
        fram_422a="EB 90 22 2C 01 12 71"
        fram_422b='10 3F C0 01 01 05 16 27 00 82 01 80 05 01' 
        fram_422d='00 AF 1D'
        fram_422c="22 2C 01 12 71"
        fram_and_AA='AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA AA'
        fram_end='C5 C5 C5 C5 C5 C5 C5 79'
        # range_index,end_index=self.get_group_range()
        work = self.get_work_model()
        enddata=self.create_form_fields()
        package_500=fram_422b+work+fram_422d+enddata+fram_and_AA#包数据
        package_500=re.findall(".{2}",package_500.replace(' ','').strip())
        package_Sum_500=fram_422b+work+fram_422d+enddata+fram_and_AA+self.getVerify(package_500)
        print(self.getVerify(package_500))
        zhen_500=fram_422c+package_Sum_500
        ALLzhen=fram_422a+package_Sum_500+self.crc16_500(zhen_500)+fram_end
        ALLzhen=ALLzhen.replace(' ','').strip()
        ALLzhenzu=' '.join(re.findall('.{2}',ALLzhen))
        self.text_area.delete("1.0", tk.END)
        self.text_area.insert(tk.END, ALLzhenzu)
        ######============信息输出到txt=============####
        paths=os.path.dirname(os.path.abspath(sys.argv[0]))
        print(paths)
        zu_name=self.get_group_range()[0]
        if zu_name==0:
            if work=='00':
               with open(paths+'temp.txt','a') as f_in:
                 f_in.write("\n"+str(self.list_count())+". "+"第一组"+" "+"长期在轨模式"+" "+self.gettime()+":  "+str(self.saveTemOnoff())+"\n"+ALLzhenzu)
            elif work=='01':
                with open(paths+'temp.txt','a') as f_in:
                  f_in.write("\n"+str(self.list_count())+". "+"第一组"+" "+"载荷工作模式"+" "+self.gettime()+":  "+str(self.saveTemOnoff())+"\n"+ALLzhenzu)
            elif work=='02':
                with open(paths+'temp.txt','a') as f_in:
                  f_in.write("\n"+str(self.list_count())+". "+"第一组"+" "+"轨控模式"+" "+self.gettime()+":  "+str(self.saveTemOnoff())+"\n"+ALLzhenzu)
            elif work=='03':
                with open(paths+'temp.txt','a') as f_in:
                  f_in.write("\n"+str(self.list_count())+". "+"第一组"+" "+"故障模式"+" "+self.gettime()+":  "+str(self.saveTemOnoff())+"\n"+ALLzhenzu)
            else:
                with open(paths+'temp.txt','a') as f_in:
                  f_in.write("\n"+str(self.list_count())+". "+"第一组"+" "+"发射前模式"+" "+self.gettime()+":  "+str(self.saveTemOnoff())+"\n"+ALLzhenzu)
        elif zu_name==29:
            if work=='00':
               with open(paths+'temp.txt','a') as f_in:
                 f_in.write("\n"+str(self.list_count())+". "+"第二组"+" "+"长期在轨模式"+" "+self.gettime()+":  "+str(self.saveTemOnoff())+"\n"+ALLzhenzu)
            elif work=='01':
                with open(paths+'temp.txt','a') as f_in:
                  f_in.write("\n"+str(self.list_count())+". "+"第二组"+" "+"载荷工作模式"+" "+self.gettime()+":  "+str(self.saveTemOnoff())+"\n"+ALLzhenzu)
            elif work=='02':
                with open(paths+'temp.txt','a') as f_in:
                  f_in.write("\n"+str(self.list_count())+". "+"第二组"+" "+"轨控模式"+" "+self.gettime()+":  "+str(self.saveTemOnoff())+"\n"+ALLzhenzu)
            elif work=='03':
                with open(paths+'temp.txt','a') as f_in:
                  f_in.write("\n"+str(self.list_count())+". "+"第二组"+" "+"故障模式"+" "+self.gettime()+":  "+str(self.saveTemOnoff())+"\n"+ALLzhenzu)
            else:
                with open(paths+'temp.txt','a') as f_in:
                  f_in.write("\n"+str(self.list_count())+". "+"第二组"+" "+"发射前模式"+" "+self.gettime()+":  "+str(self.saveTemOnoff())+"\n"+ALLzhenzu)
    
        elif zu_name==58:
            if work=='00':
               with open(paths+'temp.txt','a') as f_in:
                 f_in.write("\n"+str(self.list_count())+". "+"第三组"+" "+"长期在轨模式"+" "+self.gettime()+":  "+str(self.saveTemOnoff())+"\n"+ALLzhenzu)
            elif work=='01':
                with open(paths+'temp.txt','a') as f_in:
                  f_in.write("\n"+str(self.list_count())+". "+"第三组"+" "+"载荷工作模式"+" "+self.gettime()+":  "+str(self.saveTemOnoff())+"\n"+ALLzhenzu)
            elif work=='02':
                with open(paths+'temp.txt','a') as f_in:
                  f_in.write("\n"+str(self.list_count())+". "+"第三组"+" "+"轨控模式"+" "+self.gettime()+":  "+str(self.saveTemOnoff())+"\n"+ALLzhenzu)
            elif work=='03':
                with open(paths+'temp.txt','a') as f_in:
                  f_in.write("\n"+str(self.list_count())+". "+"第三组"+" "+"故障模式"+" "+self.gettime()+":  "+str(self.saveTemOnoff())+"\n"+ALLzhenzu)
            else:
                with open(paths+'temp.txt','a') as f_in:
                  f_in.write("\n"+str(self.list_count())+". "+"第三组"+" "+"发射前模式"+" "+self.gettime()+":  "+str(self.saveTemOnoff())+"\n"+ALLzhenzu)
        elif zu_name==87:
            if work=='00':
               with open(paths+'temp.txt','a') as f_in:
                 f_in.write("\n"+str(self.list_count())+". "+"第四组"+" "+"长期在轨模式"+" "+self.gettime()+":  "+str(self.saveTemOnoff())+"\n"+ALLzhenzu)
            elif work=='01':
                with open(paths+'temp.txt','a') as f_in:
                  f_in.write("\n"+str(self.list_count())+". "+"第四组"+" "+"载荷工作模式"+" "+self.gettime()+":  "+str(self.saveTemOnoff())+"\n"+ALLzhenzu)
            elif work=='02':
                with open(paths+'temp.txt','a') as f_in:
                  f_in.write("\n"+str(self.list_count())+". "+"第四组"+" "+"轨控模式"+" "+self.gettime()+":  "+str(self.saveTemOnoff())+"\n"+ALLzhenzu)
            elif work=='03':
                with open(paths+'temp.txt','a') as f_in:
                  f_in.write("\n"+str(self.list_count())+". "+"第一组"+" "+"故障模式"+" "+self.gettime()+":  "+str(self.saveTemOnoff())+"\n"+ALLzhenzu)
            else:
                with open(paths+'temp.txt','a') as f_in:
                  f_in.write("\n"+str(self.list_count())+". "+"第四组"+" "+"发射前模式"+" "+self.gettime()+":  "+str(self.saveTemOnoff())+"\n"+ALLzhenzu)
    def openjiemian(self):
        filetype = [('txt files', '.txt'), ('All files', '*')]
        directorys= filedialog.askopenfilenames(title='选择文件',multiple=True,filetypes=filetype)
        return  directorys
    # def import_temp(self):
    #     global  labels_entry
    #     # temp_data = {}
    #     # global labels_entry
    #     # try:
    #     with open("xx.json", 'r', encoding='utf-8') as f_temp:
    #         labels_entry = json.load(f_temp)

    #         print(labels_entry)
            #    for line in f_temp:
            #       if ':' in line:
            #         key, value = line.strip().split(':', 1)
            #         temp_data[key] = value
            #         print("aa",temp_data[key])


if __name__ == "__main__":
    root = tk.Tk()
    app = DataManagementApp(root)
    root.mainloop()
