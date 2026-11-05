"""Install the checked GP0 interception and acquisition wiring, idempotently.

Run again after System Builder regenerates design_0.v. The interception is a
maintained RTL extension, not a claim that the GUI schematic contains the IP.
The original video/NPU register pages and clocks are retained.
"""
from pathlib import Path
import re
ROOT = Path(__file__).resolve().parents[3]
EDGES = ['awaddr','awvalid','awready','wdata','wstrb','wvalid','wready',
         'bresp','bvalid','bready','araddr','arvalid','arready','rdata','rresp','rvalid','rready']
WIDTH = dict(awaddr=16,wdata=32,wstrb=4,bresp=2,araddr=16,rdata=32,rresp=2)
OUT = {'awaddr','awvalid','wdata','wstrb','wvalid','bready','araddr','arvalid','rready'}

def ports():
    result=['output wire edge_clk,edge_rst_n']
    for n in EDGES:
        w=WIDTH.get(n,1);result.append(('output' if n in OUT else 'input')+' wire '+(f'[{w-1}:0] ' if w>1 else '')+'edge_'+n)
    return ',\n    '.join(result)

def design():
    p=ROOT/'design_0/hdl/design_0.v';s=p.read_text('utf-8-sig')
    if '// EDGE_LINK_GP0_BEGIN' in s:return
    end=s.index(');',s.index('module design_0'))
    s=s[:end]+',\n    '+ports()+'\n'+s[end:]
    a=s.index('design_0_AXI_Protocol_Converter_0_Inst');b=s.index(');',a)+2
    block=s[a:b]
    fields=['awaddr','awprot','awvalid','awready','wdata','wstrb','wvalid','wready',
            'bresp','bvalid','bready','araddr','arprot','arvalid','arready','rdata','rresp','rvalid','rready']
    decl=[];connections=[]
    for n in fields:
        w=32 if n in ['awaddr','araddr','wdata','rdata'] else 4 if n=='wstrb' else 3 if n.endswith('prot') else 2 if n.endswith('resp') else 1
        old='w_port__AXI_Protocol_Converter_0__ds_axi_'+n
        if '.ds_axi_'+n+'('+old+')' not in block:raise ValueError('Generated GP0 layout changed: '+n)
        block=block.replace('.ds_axi_'+n+'('+old+')','.ds_axi_'+n+'(edge_gp0_'+n+')')
        decl.append('wire '+(f'[{w-1}:0] ' if w>1 else '')+'edge_gp0_'+n+';')
        connections+=['.s_'+n+'(edge_gp0_'+n+')','.p_'+n+'('+old+')']
    connections+=['.e_'+n+'(edge_'+n+')' for n in EDGES]
    extra='\n// EDGE_LINK_GP0_BEGIN\n'+'''\nassign edge_clk=w_port__AXI_Protocol_Converter_0__aclk;
assign edge_rst_n=w_port__AXI_Protocol_Converter_0__aresetn;
edge_axil_router u_edge_gp0(.clk(edge_clk),.rst_n(edge_rst_n),
'''+',\n'.join(connections)+');\n// EDGE_LINK_GP0_END\n'
    s=s[:a]+block+extra+s[b:]
    end=s.index(');',s.index('module design_0'))+2
    s=s[:end]+'\n// GP0 extension declarations\n'+'\n'.join(decl)+'\n'+s[end:]
    p.write_text(s,encoding='utf-8')

def acq():
    s=(ROOT/'src/acq/subsys_acq.v').read_text('utf-8-sig')
    required=['// EDGE_LINK_ACQ_BEGIN','edge_waveform #','wave_select','LINK_TEST_MODE ? 0:CONTROL_BENCH_ENABLE']
    if not all(marker in s for marker in required):
        raise ValueError('Restore maintained src/acq/subsys_acq.v before hookup; legacy generator cannot recreate WAV1/safety wiring.')

def top():
    p=ROOT/'src/system_top.v';s=p.read_text('utf-8-sig')
    if '// EDGE_LINK_TOP_BEGIN' not in s or 'IO_j12_22_reserved' not in s:
        raise ValueError('Restore maintained src/system_top.v before hookup; legacy generator cannot recreate fan-power wiring.')
    start=s.index(')(')+2;end=s.index(' );',start);portblock=s[start:end]
    clean=re.sub(r'//[^\n]*|/\*.*?\*/','',portblock,flags=re.S)
    names=re.findall(r'(?:input|output|inout)\s+(?:wire\s+)?(?:\[[^]]+\]\s*)?(\w+)',clean)
    for name,test in [('cooling_link_top',0),('cooling_link_test_top',1)]:
        wrapper='module '+name+'('+portblock+' );\nsystem_top #(.ENABLE_CAMERA(0),.ENABLE_EDGE_FEATURES(1),.LINK_TEST_MODE('+str(test)+'),.CONTROL_BENCH_ENABLE(0)) system(\n'+',\n'.join('.'+n+'('+n+')' for n in names)+'\n);\nendmodule\n'
        (ROOT/'src/edge/rtl'/f'{name}.v').write_text(wrapper,encoding='utf-8')

def projects():
    p=ROOT/'soc_prj.al';s=p.read_text('utf-8-sig')
    sources=sorted((ROOT/'src/edge/rtl').glob('*.v'))+sorted((ROOT/'src/features').glob('*.v'))
    order=300
    for file in sources:
        rel=file.relative_to(ROOT).as_posix()
        if f'Path="{rel}"' not in s:
            s=s.replace('</Verilog>',f'<File Path="{rel}"><FileInfo><Attr Name="UsedInSyn" Val="true"/><Attr Name="UsedInP&amp;R" Val="true"/><Attr Name="BelongTo" Val="design_1"/><Attr Name="CompileOrder" Val="{order}"/></FileInfo></File>\n</Verilog>');order+=1
    # TD requires deterministic unique file order and design file ownership.
    counter=[0]
    def file_order(match):
        block=match.group();counter[0]+=1
        block=re.sub(r'<Attr Name="CompileOrder" Val="\d+"/>',f'<Attr Name="CompileOrder" Val="{counter[0]}"/>',block)
        if 'UsedInSyn' in block and 'BelongTo' not in block:
            block=block.replace('<FileInfo>','<FileInfo><Attr Name="BelongTo" Val="design_1"/>')
        return block
    s=re.sub(r'<File Path="[^"]+">.*?</File>',file_order,s,flags=re.S)
    p.write_text(s,encoding='utf-8')
    old=(ROOT/'src/constraint/top_merge.sdc').read_text('utf-8-sig')
    old=old.replace('g_camera/design_top_wrapper_u/', 'design_top_wrapper_u/').replace('design_top_wrapper_u/', 'g_camera/design_top_wrapper_u/')
    (ROOT/'src/constraint/top_merge.sdc').write_text(old,encoding='utf-8')
    for name in ['cooling_link','cooling_link_test']:
        variant=s.replace('<Name>soc_prj</Name>',f'<Name>{name}</Name>').replace('<LABEL>system_top</LABEL>',f'<LABEL>{name}_top</LABEL>').replace('<MODULE>system_top</MODULE>',f'<MODULE>{name}_top</MODULE>')
        variant=variant.replace('src/constraint/top_merge.sdc','src/edge/constraints/link.sdc')
        def activate(match):
            block=match.group()
            if re.search(r'Path="src/(edge/rtl|features|control|acq)/',block):
                block=re.sub(r'<Attr Name="AutoExcluded" Val="true"/>\s*','',block)
            return block
        variant=re.sub(r'<File Path="[^"]+">.*?</File>',activate,variant,flags=re.S)
        (ROOT/f'{name}.al').write_text(variant,encoding='utf-8')

if __name__=='__main__':
    design();acq();top();projects();print('Edge GP0/CDC/CSR/features wired; link variants created.')
