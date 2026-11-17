"""Exact synthetic child links, autocommit FK state and native comparison outcomes."""
from pathlib import Path
import json,html
P=Path(__file__).parent;s=json.loads((P/'summary.json').read_text());t=json.loads((P/'sqlite-trace.json').read_text());old=next(x for x in t['cases']['old']if x['statement']=='DROP TABLE `parents`');fixed=next(x for x in t['cases']['fixed']if x['statement']=='DROP TABLE `parents`');assert old['foreignKeys']==1 and old['childRows']==[];assert fixed['foreignKeys']==0 and len(fixed['childRows'])==3
children=s['cases']['fixed']['local_rows']['children'];assert children==[[1,1],[2,1],[3,2]];data={'source':'Original retained generated SQL and newly executed native reports; owned synthetic rows only','childrenBefore':children,'oldDrop':old,'fixedDrop':fixed,'cases':s['cases'],'inputs':s['input_sha256'],'sqlite':s['sqlite']};(P/'figure-data.json').write_text(json.dumps(data,indent=2)+'\n')
def make(mobile):
 W,H=(420,1130)if mobile else(1160,740);o=[];add=o.append
 def text(x,y,v,size=16,c='#242430',weight=400):add(f'<text x="{x}" y="{y}" font-size="{size}" fill="{c}" font-weight="{weight}">{html.escape(str(v))}</text>')
 def line(x,y,X,Y,c='#bdc2c8',w=1):add(f'<line x1="{x}" y1="{y}" x2="{X}" y2="{Y}" stroke="{c}" stroke-width="{w}"/>')
 def box(x,y,w,h,label,fill='#eeebf7',stroke='#938ab5'):
  add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="3" fill="{fill}" stroke="{stroke}"/>');text(x+10,y+h/2+5,label,14)
 desc='A synthetic SQLite fixture has two parent IDs and three child links: child one to parent one, child two to parent one, and child three to parent two. In the retained old generated migration, foreign-key enforcement is on at DROP TABLE parents, so cascading deletes remove all child rows. The rebuilt parent IDs remain and the final integrity and foreign-key checks pass. Keepstep reports changed with exit one. The corrected generated SQL and unchanged controls retain all three children and report matched with exit zero. This applies SQL in autocommit without an outer migration-runner transaction.'
 add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title desc"><title id="title">Parent IDs stay; child rows disappear</title><desc id="desc">{desc}</desc><style>text{{font-family:Arial,"DejaVu Sans",sans-serif}}</style><rect width="100%" height="100%" fill="#f8f6f1"/>')
 text(28,35,'Keepstep / declared behavior on SQLite copies',13,'#58606a');text(28,79,'Parent IDs stay.',32,'#171923',600);text(28,118,'Child rows disappear.',32,'#171923',600)
 gx,gy=28,175;text(gx,gy,'Before / owned synthetic rows',16,'#171923',600)
 parentpos={1:(88,220),2:(260,220)}
 for child,parent in children:
  x=38+(child-1)*118;px,py=parentpos[parent];line(px+45,py+40,x+50,310,'#938ab5',2)
 for parent,(x,y)in parentpos.items():box(x,y,100,40,f'parent {parent}')
 for child,parent in children:box(38+(child-1)*118,310,104,58,f'child {child} → {parent}',fill='#fff',stroke='#938ab5')
 text(28,399,'Two parents; three exact child-parent links.',12,'#58606a')
 dx,dy=(28,455)if mobile else(485,185);text(dx,dy,'At the old parent-table drop',17,'#171923',600);box(dx,dy+20,330,43,'foreign_keys = ON',fill='#fff0eb',stroke='#ae3542');box(dx,dy+82,330,43,'DROP TABLE parents',fill='#fff0eb',stroke='#ae3542');text(dx,dy+156,'ON DELETE CASCADE removes 3 children.',13,'#9b2737',600);text(dx,dy+185,'No outer transaction in this replay.',12,'#58606a')
 cy=705 if mobile else 490;text(28,cy,'Final / integrity + FK checks pass',17,'#171923',600)
 for i,(name,label)in enumerate([('old','Old generated SQL'),('fixed','Corrected generated SQL'),('unchanged','Unchanged control')]):
  x,y,w=(28,cy+25+i*95,364)if mobile else(28+i*374,cy+27,350);case=s['cases'][name];count=len(case['local_rows']['children']);changed=name=='old';add(f'<rect data-case="{name}" x="{x}" y="{y}" width="{w}" height="{82 if mobile else 115}" fill="{chr(35)+("fff0eb"if changed else"edf3ec")}" stroke="{chr(35)+("b96666"if changed else"91a18c")}"/>');text(x+14,y+25,label,14,'#242430',600);text(x+14,y+51,f'Children 3 → {count}',19,'#9b2737'if changed else'#31643b',600);text(x+14,y+72,f'{case["status"]}; CLI exit {case["exit"]}',13,'#58606a')
 ny=1050 if mobile else 680;text(28,ny,'Parent IDs 2 → 2; unrelated row 1 → 1.',12,'#58606a');text(28,ny+25,'Only this declared workload; changed defaults are excluded.',12,'#58606a');text(28,H-19,'Retained generated SQL, direct SQLite replay. No production safety claim.',11,'#58606a');add('</svg>');(P/('children-mobile.svg'if mobile else'children.svg')).write_text(''.join(o))
make(False);make(True)
