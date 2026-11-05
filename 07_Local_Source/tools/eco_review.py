"""Review the two physical comparator output changes; preserve all connected nets."""
import re,json

def parse_cell(block):
    left,pins=block.split('Input Pin(s):',1);ins,outs=pins.split('Output Pin(s):',1)
    attrs={k.strip():v.strip() for k,v in re.findall(r'^RUN-1001 :\s+([A-Za-z][A-Za-z0-9 _]*)\s+\|\s*([^\n]+)',left,re.M)}
    for k in ('Attribute','Function'):attrs.pop(k,None)
    def parse(text):
        return {k:(loc.strip(),net.strip()) for k,loc,net in re.findall(r'^RUN-1001 :\s+\d+\s*\|\s*(\w+)\s*\|([^|]*)\|\s*([^\n]+)',text,re.M)}
    return dict(attrs=attrs,inputs=parse(ins),outputs=parse(outs))

def modification(text,names):
    result={}
    for name,net in names.items():
        before=text.split('P50_BEFORE '+name+'\n',1)[1].split('P50_PROPERTY_KEYS ',1)[0]
        after=text.split('P50_AFTER '+name+'\n',1)[1]
        after=re.split(r'P50_BEFORE |RUN-1002 : start command "export_db',after,1)[0]
        a,b=parse_cell(before),parse_cell(after)
        assert a['attrs']['Model']=='DR1_PHY_LSLICE' and a['attrs']['LUTMODE']==':DLUT5'
        assert a['attrs']['OFA_SD']==':F7CY'
        assert {k:v[1] for k,v in a['outputs'].items() if v[1]!='Nil'}=={'ofa':net}
        assert a['inputs']==b['inputs'] and a['outputs']==b['outputs']
        changed={k:(a['attrs'].get(k),b['attrs'].get(k)) for k in set(a['attrs'])|set(b['attrs']) if a['attrs'].get(k)!=b['attrs'].get(k)}
        assert set(changed)=={'LUT5A','LUT5B'},changed
        assert b['attrs']['LUT5A']==b['attrs']['LUT5B']=='=0' and b['attrs']['OFA_SD']==':F7CY'
        result[name]=dict(before=a,after=b,driven_net=net,changed_attributes=changed)
    calls=re.findall(r'start command "set_inst_attr ([^"]+)"',text)
    assert len(calls)==4
    for name in names:
        assert '-inst '+name+' -attr_key LUT5A -attr_value =0' in calls
        assert '-inst '+name+' -attr_key LUT5B -attr_value =0' in calls
    assert text.splitlines().count('P50_CONST_COMPARATORS_EXPORTED_NOT_BITGEN')==1
    return result

def reload(text,plan):
    for name,info in plan['physical_changes'].items():
        b=text.split('P50_RELOAD_CELL '+name+'\n',1)[1].split('P50_RELOAD_END',1)[0]
        assert json.loads(json.dumps(parse_cell(b)))==info['after'],name
    assert 'ERROR:' not in text and 'WARNING:' not in text
