from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor, Color, white
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from PIL import Image
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parent
OUT=ROOT.parents[1]/'output'/'pdf'
OUT.mkdir(parents=True,exist_ok=True)
FONT=Path('C:/Windows/Fonts')
for name,file in [('Body','arial.ttf'),('Bold','arialbd.ttf'),('Italic','ariali.ttf')]:
 pdfmetrics.registerFont(TTFont(name,str(FONT/file)))
pdfmetrics.registerFontFamily('Body',normal='Body',bold='Bold',italic='Italic',boldItalic='Bold')
W,H=A4; M=47; CW=W-2*M
NAVY=HexColor('#18334c'); INK=HexColor('#263746'); MUTED=HexColor('#586b79')
COLORS={'PROJECT':NAVY,'WRITER':HexColor('#2465a4'),'BASE':HexColor('#a83d43'),'CALC':HexColor('#25784e')}
pdf=OUT/'Class_10_IT_Project_LibreOffice_Writer_Base_Calc.pdf'
c=canvas.Canvas(str(pdf),pagesize=A4)
c.setTitle('Class 10 IT Project - LibreOffice Writer, Base and Calc')
c.setAuthor('Class 10 - Student Project')
c.setSubject('Illustrated practical project with official LibreOffice interface screenshots')
PAGE=0; y=0; section='PROJECT'; figure=0
def para(text,size=11,leading=16,space=10,color=INK,font='Body',indent=0):
 global y
 st=ParagraphStyle('p',fontName=font,fontSize=size,leading=leading,textColor=color,spaceAfter=space)
 p=Paragraph(text,st); _,h=p.wrap(CW-indent,800)
 if y-h<61: raise RuntimeError(f'Page {PAGE} overflow: {text[:70]} at {y}')
 p.drawOn(c,M+indent,y-h); y-=h+space
def title(text):
 para(text,25,30,16,NAVY,'Bold')
def sub(text): para(text,12,16,7,COLORS[section],'Bold')
def steps(items):
 for i,t in enumerate(items,1): para(f'<b>{i}.</b> {t}',10.5,14.5,5,indent=3)
 ygap(5)
def ygap(n):
 global y
 y-=n
def box(label,text):
 global y
 st=ParagraphStyle('box',fontName='Body',fontSize=10.2,leading=14,textColor=INK)
 p=Paragraph(f'<b>{label}</b>  {text}',st); _,h=p.wrap(CW-24,800)
 if y-h-22<61: raise RuntimeError(f'Box overflow {PAGE}')
 c.setFillColor(HexColor('#f0f4f7')); c.roundRect(M,y-h-20,CW,h+20,5,fill=1,stroke=0)
 p.drawOn(c,M+12,y-h-10); y-=h+30
def table(rows,widths=None,fs=10):
 global y
 st=ParagraphStyle('cell',fontName='Body',fontSize=fs,leading=fs+4,textColor=INK)
 cells=[[Paragraph(escape(str(v)),st) for v in row] for row in rows]
 t=Table(cells,colWidths=widths or [CW/len(rows[0])]*len(rows[0]),hAlign='LEFT')
 t.setStyle(TableStyle([
 ('BACKGROUND',(0,0),(-1,0),HexColor('#e4edf4')),
 ('ROWBACKGROUNDS',(0,1),(-1,-1),[white,HexColor('#f7f9fb')]),
 ('LINEBELOW',(0,0),(-1,0),0.8,COLORS[section]),
 ('LINEBELOW',(0,1),(-1,-1),0.25,HexColor('#d8e1e7')),
 ('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),8),
 ('RIGHTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
 _,h=t.wrap(CW,800)
 if y-h<61: raise RuntimeError(f'Table overflow {PAGE}: {y-h}')
 t.drawOn(c,M,y-h); y-=h+12
def shot(name,caption,maxh=200,maxw=None):
 global y,figure
 p=ROOT/'assets'/name
 im=Image.open(p); iw,ih=im.size
 scale=min((maxw or CW-12)/iw,maxh/ih)
 w,h=iw*scale,ih*scale; x=M+(CW-w)/2
 if y-h-40<61: raise RuntimeError(f'Image overflow {PAGE} {name}')
 c.setStrokeColor(HexColor('#d1dbe4')); c.setLineWidth(.6)
 c.rect(x-3,y-h-3,w+6,h+6,fill=0,stroke=1)
 c.drawImage(str(p),x,y-h,w,h,mask='auto'); y-=h+12; figure+=1
 para(f'Fig. {figure}. {caption} <i>Official guide screenshot; reference example.</i>',8.3,11.2,10,MUTED)
def page(sec,name):
 global PAGE,y,section
 if PAGE: c.showPage()
 PAGE+=1; section=sec; y=H-92
 c.setFillColor(COLORS[sec]); c.rect(0,H-12,W,12,fill=1,stroke=0)
 c.setFillColor(MUTED); c.setFont('Bold',8)
 c.drawString(M,H-42,'CLASS 10  /  INFORMATION TECHNOLOGY')
 c.drawRightString(W-M,H-42,sec)
 c.setStrokeColor(HexColor('#d9e2e9')); c.line(M,47,W-M,47)
 c.setFillColor(MUTED); c.setFont('Body',8)
 c.drawString(M,31,'LibreOffice Applications: Writer, Base and Calc')
 c.drawRightString(W-M,31,f'{PAGE:02d}')
 c.bookmarkPage(f'p{PAGE}'); c.addOutlineEntry(name,f'p{PAGE}',0,False)
 title(name)

page('PROJECT','Information Technology Project')
ygap(35)
para('LIBREOFFICE',35,41,6,NAVY,'Bold')
para('Writer, Base and Calc',25,32,20,NAVY)
para('Class 10  |  Illustrated practical project',12,18,30,MUTED)
for n,label,desc in [('01','WRITER','Create and format documents'),('02','BASE','Store and retrieve information'),('03','CALC','Calculate, analyse and present data')]:
 c.setFillColor(COLORS[label]); c.roundRect(M,y-53,CW,53,5,fill=1,stroke=0)
 c.setFillColor(white); c.setFont('Bold',13); c.drawString(M+16,y-22,n+'   '+label)
 c.setFont('Body',10); c.drawString(M+16,y-40,desc); y-=66
ygap(20)
for t in ['Submitted by: _______________________________________','Class and Section: __________    Roll No.: __________','School: ____________________________________________','Submitted to: _______________________________________','Academic Year: _____________________________________']:
 para(t,11,16,13)

page('PROJECT','Bonafide Certificate')
ygap(35)
para('This is to certify that <b>________________________________</b>, a bonafide student of <b>Class 10, Section ______</b>, Roll No. <b>______</b>, of <b>________________________________________________</b>, has successfully completed the Information Technology project entitled:',12,21,25)
para('"LibreOffice Applications: Writer, Base and Calc"',17,24,25,NAVY,'Bold')
para('The project has been completed during the academic year <b>________________</b> under the guidance of <b>________________________________</b> and is submitted as part of the school\'s academic requirements.',12,21,30)
para('Place: __________________________',12,20,12)
para('Date: ___________________________',12,20,12)
y=220
c.setStrokeColor(INK); c.line(M,185,M+200,185); c.line(W-M-200,185,W-M,185)
c.setFont('Bold',11); c.drawString(M,165,"Examiner's Signature"); c.drawString(W-M-200,165,"Principal's Signature")
c.setFont('Body',10); c.drawString(M,142,'Name: _____________________'); c.drawString(W-M-200,142,'Name: _____________________')
c.drawString(W-M-200,112,'School Seal')

page('PROJECT','Acknowledgement')
ygap(40)
para('I would like to express my sincere gratitude to my Information Technology teacher, <b>________________________________</b>, for their guidance and support in completing my project on <b>"LibreOffice Applications: Writer, Base and Calc."</b>',12,22,25)
para('I am also thankful to our Principal, <b>________________________________</b>, and my school for providing the resources and opportunity to complete this project.',12,22,25)
para('Finally, I thank my parents and friends for their encouragement and help. This project helped me understand how to create documents, manage databases and work with spreadsheets using LibreOffice.',12,22,25)
ygap(45)
para('Name: ____________________________________',12,20,16)
para('Class and Section: __________________________',12,20,16)
para('Roll No.: __________________________________',12,20,16)

page('PROJECT','Table of Contents')
para('The project follows the sequence Writer, Base and Calc. The page numbers below match the printed page numbers.',10.5,15,17,MUTED)
table([
 ['S. No.','Contents','Page No.'],
 ['1','Bonafide Certificate','2'],['2','Acknowledgement','3'],['3','Introduction to LibreOffice','5'],
 ['4','LibreOffice Writer: Introduction and Features','6'],['5','Creating and Formatting Documents in Writer','7-10'],
 ['6','LibreOffice Base: Introduction and Features','11'],['7','Creating Databases and Tables in Base','12-13'],
 ['8','Queries, Forms and Reports in Base','14-16'],['9','LibreOffice Calc: Introduction and Features','17'],
 ['10','Formulas, Functions and Charts in Calc','18-22'],['11','Conclusion','23'],['12','Bibliography','24']],
 [45,CW-111,66],10.5)
ygap(18)
box('Picture guide','Pictures show real LibreOffice windows from the official documentation. The guides use their own sample data; the school exercises in this project use original example data. Icons and layouts can differ between versions.')

page('PROJECT','Introduction to LibreOffice')
para('LibreOffice is a free and open-source office suite. It provides applications for writing documents, working with numbers, making presentations, drawing and managing databases. This project focuses on three applications used for school and everyday tasks.')
table([['Application','Main purpose','Native file format'],['Writer','Documents, letters and reports','.odt'],['Base','Databases, tables, queries, forms and reports','.odb'],['Calc','Spreadsheets, calculations and charts','.ods']],[85,292,CW-377])
sub('Objectives of the project')
steps(['Create an organised document using text formatting, headings, tables and pictures.','Design a student database, enter records and retrieve selected information.','Prepare a marks spreadsheet, calculate results and display data in a chart.','Save editable files and prepare clear PDF or printed output.'])
sub('A connected school example')
para('A school can use Writer for an activity report, Base for student records and Calc for examination results. Each application handles a different part of the same information task.')
box('Working method','Each practical includes an aim, steps and an expected result. Use the classic menu interface when following menu paths. All names and marks in the exercises are fictional.')
para('Software reference: LibreOffice Getting Started Guide 24.8. Chart illustrations are from the Calc Guide 24.2. No particular school board is assumed.',9.5,14,10,MUTED)

page('WRITER','Writer: Introduction and Features')
para('Writer is the word-processing application in LibreOffice. It is used to prepare letters, notices, assignments and reports. The document is shown as pages, so its layout can be checked before printing.')
shot('writer_002.png','Writer workspace with labelled menus, toolbars, Sidebar and Status bar.',240)
table([['Part of the window','Use'],['Menu bar and toolbars','Open commands and common formatting tools.'],['Document area','Type and edit the contents of the page.'],['Sidebar','Change properties and apply styles.'],['Status bar','Check document information and adjust zoom.']],[145,CW-145],10)
box('Key features','Text formatting, spelling checks, styles, tables, pictures, automatic contents, mail merge and PDF export.')

page('WRITER','Practical 1: Create a School Report')
sub('Aim')
para('Create and save a one-page report about a school cleanliness drive.')
steps(['Open LibreOffice and choose <b>Writer Document</b>, or use <b>File &gt; New &gt; Text Document</b>.','Type the heading <b>School Cleanliness Drive</b>. Below it, type the date, venue and a short description.','Select the heading, make it bold, use an 18-point font and centre it. Set the body text to 12 points.','Use left alignment for the body and add a numbered list of three activities.','Press <b>Ctrl+S</b>, enter <b>Cleanliness_Report.odt</b>, select a folder and save.'])
shot('writer_020.png','A Writer formatting toolbar; the available tools depend on the selected toolbar.',28)
sub('Sample text to type')
box('Report','Our class organised a cleanliness drive in the school garden. Students collected litter, separated waste and made awareness posters. The activity encouraged teamwork and care for our surroundings.')
shot('writer_017.png','Spelling dialog: inspect the suggested correction before choosing Correct.',160)
para('<b>Expected result:</b> A readable report with a clear heading, a paragraph and a numbered list. Press <b>F7</b> to check spelling and save again.',10.5,15)

page('WRITER','Practical 2: Styles and Contents')
sub('Aim')
para('Organise a longer document using headings, an automatic table of contents and a page header.')
steps(['Create three sections: <b>Introduction</b>, <b>Activities</b> and <b>Conclusion</b>. Add a short paragraph below each.','Click each section title and apply the <b>Heading 1</b> paragraph style from the style list. Use <b>Heading 2</b> for subheadings.','Place the cursor near the beginning. Choose <b>Insert &gt; Table of Contents and Index &gt; Table of Contents, Index or Bibliography</b>. Select the table-of-contents type and confirm.','After editing headings, right-click inside the contents and choose <b>Update Table of Contents</b>.','Open <b>Format &gt; Page Style</b>, use the <b>Header</b> tab, enable the header and confirm. Type a short project title in the header.'])
shot('writer_028.png','Page Style dialog, Header tab, used to control the page header.',200)
box('Expected result','The section titles share one style and appear in an automatically generated contents list. A consistent header appears on pages using the same page style.')
para('<b>Why styles help:</b> Changing a heading style updates all headings that use it. This keeps long projects consistent and makes navigation easier.',10.5,15)

page('WRITER','Practical 3: Tables and Pictures')
sub('Aim')
para('Add an activity table and a relevant picture to the school report.')
steps(['Place the cursor below the report. Choose <b>Table &gt; Insert Table</b> or press <b>Ctrl+F12</b>. Create 3 columns and 4 rows.','Enter the sample data shown below. Make the first row bold and adjust the column widths.','Choose <b>Insert &gt; Image</b>, select a suitable picture saved on your computer and click Open.','Resize using a corner handle and keep the picture in proportion. For a simple report, right-click the image and choose <b>Anchor &gt; As Character</b>.','Use a picture that you created or have permission to use. Add a short caption using <b>Insert &gt; Caption</b>.'])
sub('Sample table output')
table([['Activity','Participants','Duration'],['Garden cleaning','Class 10 students','30 minutes'],['Waste segregation','Eco Club','20 minutes'],['Poster display','Art group','15 minutes']],[180,190,CW-370])
box('Picture to insert','Use a photograph of a school garden, or a simple drawing of three labelled waste bins. A suitable caption is: Figure 1: Keeping our school surroundings clean.')
sub('Expected result')
para('The report contains an aligned table, a picture of suitable size and an informative caption. The image stays close to its related text.')
sub('Check before saving')
para('Make sure no table column extends beyond the page margin. Use Print Preview to check the picture, caption and page breaks. Save the updated document as <b>Cleanliness_Report.odt</b>.')

page('WRITER','Practical 4: Edit and Export')
sub('Aim')
para('Correct repeated text and export the completed report as a PDF.')
steps(['Press <b>Ctrl+H</b> to open Find and Replace. Enter <b>garbage</b> in Find and <b>waste</b> in Replace.','Use <b>Find Next</b> to inspect each match, then replace suitable occurrences. Review the text after any Replace All operation.','Check spelling, headings, page breaks and image captions. Save the editable <b>.odt</b> file.','Choose <b>File &gt; Export As &gt; Export as PDF</b>. Check the page range and export as <b>Cleanliness_Report.pdf</b>.','Open the exported PDF and confirm that its text and pictures appear correctly.'])
shot('writer_013.png','Find and Replace dialog for searching and changing repeated text.',190)
box('Expected result','An editable Writer document and a separate PDF that preserves the page layout for sharing or printing.')
sub('Extension: Mail merge')
para('Mail merge combines one standard letter with a list of recipients. For example, a school invitation can include a different student name on each copy. Start with <b>Tools &gt; Mail Merge Wizard</b>, choose the document and connect the address list. Preview the merged copies before printing.',10.5,15)

page('BASE','Base: Introduction and Features')
para('Base is the database application in LibreOffice. It can manage an embedded database or connect to an external database. A database organises related information so that records can be found, updated and presented efficiently.')
shot('base_004.png','Base main window, with database objects on the left and tasks on the right.',235)
table([['Database object','Purpose'],['Table','Stores records in rows and fields in columns.'],['Query','Selects or calculates information from stored data.'],['Form','Provides a convenient interface for data entry.'],['Report','Presents selected information in a printable layout.']],[100,CW-100])
box('Project example','Create Student_Database.odb containing a Students table. Use it to view student marks, find high-scoring students, enter records with a form and print a report.')

page('BASE','Practical 5: Create a Database')
sub('Aim')
para('Create an empty database file for student information.')
steps(['Open LibreOffice and choose <b>Base Database</b>, or choose <b>File &gt; New &gt; Database</b>.','In the Database Wizard, choose <b>Create a new database</b>. Keep the supported embedded database option available in your installation. Click Next.','For this standalone exercise, registration is optional. Keep <b>Open the database for editing</b> selected.','Click Finish and save the file as <b>Student_Database.odb</b>.','The Base window opens. Select <b>Tables</b> in the left panel to begin creating a table.'])
shot('base_005.png','Database Wizard: the guide example shows an embedded database choice.',225)
box('Expected result','A saved Student_Database.odb file and an open Base window ready for table creation.')
para('<b>Setup note:</b> Some Base features, including certain database engines and Report Builder, require a compatible Java runtime. If prompted, select an installed runtime under Tools &gt; Options &gt; LibreOffice &gt; Advanced.',10,14)
para('The database engine shown in your installation may differ from the one in the reference screenshot.',9.5,14,10,MUTED)

page('BASE','Practical 6: Tables and Records')
para('<b>Aim:</b> Design the Students table with a unique student number and enter four records.',10.5,15,8)
steps(['Select <b>Tables &gt; Create Table in Design View</b>. Add the fields listed below.','Right-click the row selector for <b>StudentID</b> and choose <b>Primary Key</b>. Save the table as <b>Students</b>.','Open Students, enter the records shown below and save your work. For this exercise, type the StudentID values manually.'])
table([['Field name','Data type','Purpose'],['StudentID','Integer','Primary key; unique number'],['StudentName','Text [VARCHAR], length 50','Name of the student'],['ClassSection','Text [VARCHAR], length 10','Class and section'],['ITMarks','Integer','Marks out of 100']],[95,180,CW-275],9)
shot('base_012.png','A key symbol identifies a primary key. The guide uses FuelID and AutoValue; this exercise uses manually entered StudentID values.',115)
table([['StudentID','StudentName','ClassSection','ITMarks'],['101','Aarav','10-A','86'],['102','Diya','10-A','92'],['103','Kabir','10-B','74'],['104','Meera','10-B','88']],[80,175,130,CW-385],9)
box('Field, record and key','A field is one attribute, such as ITMarks. A record is one complete student row. A primary key must be unique and cannot be empty. Student names alone are unsuitable because names can repeat.')

page('BASE','Practical 7: Retrieve Data with Queries')
para('<b>Aim:</b> Display the students who scored 85 or more in Information Technology.',10.5,15)
steps(['Click <b>Queries &gt; Create Query in Design View</b>. Add the Students table.','Add <b>StudentID</b>, <b>StudentName</b> and <b>ITMarks</b> to the design grid. In the Criterion row under ITMarks, enter <b>&gt;=85</b>.','Sort ITMarks in descending order, run the query and save it as <b>High_Scorers</b>.'])
sub('Equivalent SQL example')
box('SQL','SELECT "StudentID", "StudentName", "ITMarks"<br/>FROM "Students"<br/>WHERE "ITMarks" &gt;= 85<br/>ORDER BY "ITMarks" DESC;')
table([['StudentID','StudentName','ITMarks'],['102','Diya','92'],['104','Meera','88'],['101','Aarav','86']],[95,260,CW-355],9.5)
shot('base_061.png','The Query Wizard is an alternative way to choose fields. The official example uses a CD-Collection table.',155)
para('<b>Expected result:</b> Three matching records appear in descending mark order. The query displays selected data; it does not remove the other student record.',10,14)

page('BASE','Practical 8: Create a Data Entry Form')
sub('Aim')
para('Create a form that makes student data easy to enter and review.')
steps(['Select <b>Forms &gt; Use Wizard to Create Form</b>. Choose the Students table.','Move StudentID, StudentName, ClassSection and ITMarks to the selected fields list. Skip the subform for this simple exercise.','Choose a columnar arrangement, keep a clear style and allow the form to display existing records.','Save it as <b>Student_Entry</b> and finish the wizard.','Use the navigation buttons to inspect the four records. Add a record: <b>105, Riya, 10-A, 90</b>. Check that it appears in Students.'])
shot('base_021.png','Form Wizard field selection. Choose Students for the project instead of the guide example.',175)
shot('base_024.png','Form Wizard layout choices for arranging labels and controls.',120,maxw=180)
box('Expected result','A labelled Student_Entry form that displays student data and allows a new record to be entered. The Students table now contains five records.')

page('BASE','Practical 9: Prepare a Report')
sub('Aim')
para('Prepare a printable report using the High_Scorers query.')
steps(['Run High_Scorers again after adding Riya. It should now include four students.','Select <b>Reports &gt; Use Wizard to Create Report</b>. Choose the High_Scorers query and include StudentID, StudentName and ITMarks.','Keep clear field labels, skip grouping and sort ITMarks in descending order.','Choose a suitable layout and title it <b>IT High Scorers</b>. Save the report. A dynamic report can use updated data when generated again.','Open the report and check its heading, field values and page layout before printing.'])
shot('base_065.png','Report Wizard field selection. Select the project query in Tables or queries.',165)
sub('Expected report data')
table([['StudentID','StudentName','ITMarks'],['102','Diya','92'],['105','Riya','90'],['104','Meera','88'],['101','Aarav','86']],[95,260,CW-355],9.5)
box('A relational database','If another table stores attendance, its StudentID field can refer to Students.StudentID. This foreign key links each attendance record to a student and avoids repeatedly storing the student name.')

page('CALC','Calc: Introduction and Features')
para('Calc is the spreadsheet application in LibreOffice. A spreadsheet stores data in cells arranged in rows and columns. It is useful for marksheets, budgets, calculations and charts.')
shot('calc_002.png','Calc main window with labelled columns, rows, Formula bar and sheet tabs.',240)
table([['Term','Meaning'],['Cell','Intersection of a row and column, such as B2.'],['Range','A group of cells, such as B2:D5.'],['Formula','An expression beginning with = that calculates a value.'],['Function','A named calculation, such as SUM or AVERAGE.']],[100,CW-100])
box('Key features','Automatic calculation, functions, charts, sorting, filtering, multiple sheets and tools for exploring changes in data. Save editable spreadsheets in the .ods format.')

page('CALC','Practical 10: Prepare a Marksheet')
para('<b>Aim:</b> Enter marks for three subjects and calculate totals and percentages.',10.5,15)
steps(['Open <b>Calc Spreadsheet</b>, or choose <b>File &gt; New &gt; Spreadsheet</b>. Rename Sheet1 to <b>Marks</b>.','In row 1, enter the headings shown below. Enter the four student records in rows 2 to 5. Each subject is out of 100.','In <b>E2</b>, type <b>=SUM(B2:D2)</b>. In <b>F2</b>, type <b>=E2/300</b> and apply Percentage format.','Copy E2:F2 down to row 5 using the fill handle. Make the heading row bold, add borders and save as <b>Class10_Marks.ods</b>.'])
shot('calc_003.png','Formula bar, used to view or edit the contents of the active cell.',27)
sub('Sample output and cell positions')
table([['A: Name','B: English','C: Maths','D: IT','E: Total','F: Percent'],['Aarav','78','84','86','248','82.67%'],['Diya','89','94','92','275','91.67%'],['Kabir','72','68','74','214','71.33%'],['Meera','85','81','88','254','84.67%']],[95,80,75,65,80,CW-395],9)
box('Percentage format','F2 contains about 0.8267. Percentage formatting displays it as 82.67%. Do not also multiply this formula by 100 when using Percentage format.')
sub('Expected result')
para('The totals and percentages match the table. Changing a subject mark automatically updates the related total and percentage.')
para('<b>Check:</b> Three marks of 100 must produce a total of 300 and a percentage of 100%.',10.5,15)

page('CALC','Practical 11: Functions and References')
para('<b>Aim:</b> Summarise the marksheet and use cell references correctly.',10.5,15)
table([['Task','Formula','Expected value'],['Class total of IT marks','=SUM(D2:D5)','340'],['Average IT mark','=AVERAGE(D2:D5)','85'],['Highest IT mark','=MAX(D2:D5)','92'],['Lowest IT mark','=MIN(D2:D5)','74'],['Number of numeric IT marks','=COUNT(D2:D5)','4'],['Result for Aarav, based on IT','=IF(D2>=33;"Pass";"Needs practice")','Pass']],[150,245,CW-395],9)
para('Enter the summary formulas below the marksheet. Use the Function Wizard button near the Formula bar to browse functions and check their arguments.',10.5,15)
shot('calc_045.png','Function Wizard helps select a function and supply its arguments.',165)
box('Relative and absolute references','B2 changes to B3 when copied down one row. $B$2 stays fixed. For a fixed maximum total, type 300 in H2 and use =E2/$H$2 in F2 before copying the formula down.')
para('The IF example assumes a practice pass mark of 33 out of 100. Some installations use commas instead of semicolons between function arguments.',9.5,14,8,MUTED)

page('CALC','Practical 12: Sort and Filter Data')
sub('Aim')
para('Arrange students by total marks and display only students meeting a condition.')
steps(['Select the complete marks table <b>A1:F5</b>. Choose <b>Data &gt; Sort</b>. Confirm that the range contains a heading row.','Select the <b>Total</b> column and choose descending order. Click OK. Keep every student\'s row together.','The expected order is <b>Diya (275), Meera (254), Aarav (248), Kabir (214)</b>.','With the complete table selected, choose <b>Data &gt; AutoFilter</b>. Open the filter arrow on IT and use its Standard Filter option, or open <b>Data &gt; More Filters &gt; Standard Filter</b>.','Set the condition <b>IT &gt;= 85</b>. The visible students should be Diya, Meera and Aarav. Clear the filter to show all records.'])
shot('calc_044.png','Sort dialog: select a sort column and choose ascending or descending order.',215)
box('Expected result','Sorting changes the order of the complete records. Filtering temporarily hides rows that do not match the condition; it keeps their data in the spreadsheet.')
para('For the next practical, use the original student order from page 18. Re-enter the small chart table if you have already sorted the marksheet.',10,14)

page('CALC','Practical 13: Create a Chart')
sub('Aim')
para('Compare student total marks using a column chart.')
steps(['In a clear area or a new sheet, enter two columns headed <b>Student</b> and <b>Total</b>. Use Aarav 248, Diya 275, Kabir 214 and Meera 254.','Select the table including its headings and choose <b>Insert &gt; Chart</b>.','Choose a <b>Column</b> chart. Confirm that the first row supplies the heading and the first column supplies category labels.','Set the title to <b>Student Total Marks</b>, the horizontal axis to <b>Student</b> and the vertical axis to <b>Marks out of 300</b>. Click Finish.'])
shot('chart_004.png','Chart Wizard, Chart Type step: choose a column chart.',145)
sub('Expected chart - project sample data')
global_y=y
chart_h=147; bx=M+35; by=y-chart_h; bw=CW-60
c.setStrokeColor(HexColor('#a4b1ba')); c.setLineWidth(.5)
for mark in [0,100,200,300]:
 yy=by+22+mark/300*105
 c.setStrokeColor(HexColor('#dce3e8')); c.line(bx,yy,bx+bw,yy)
 c.setFillColor(MUTED); c.setFont('Body',8); c.drawRightString(bx-7,yy-3,str(mark))
for i,(name,val) in enumerate([('Aarav',248),('Diya',275),('Kabir',214),('Meera',254)]):
 xx=bx+26+i*(bw/4)
 c.setFillColor(COLORS['CALC']); c.rect(xx,by+22,42,val/300*105,fill=1,stroke=0)
 c.setFillColor(INK); c.setFont('Body',8); c.drawCentredString(xx+21,by+val/300*105+27,str(val)); c.drawCentredString(xx+21,by+8,name)
y-=chart_h+8
para('Illustrative output drawn from the project data. Diya has the highest total, 275 out of 300.',9,13,8,MUTED)
box('Choose a useful chart','Column charts compare categories. Line charts show changes over time. Pie charts show parts of a whole. Keep titles and labels readable.')

page('CALC','Practical 14: Goal Seek and Printing')
sub('Part A: Explore a target with Goal Seek')
para('Create a separate sheet named <b>Target</b>. In B1 enter 78, in B2 enter 84, in B3 enter 86, and in B4 enter <b>=SUM(B1:B3)</b>.',10.5,15)
steps(['Select B4 and open <b>Tools &gt; Goal Seek</b>. Set Formula cell to <b>$B$4</b>, Target value to <b>270</b> and Variable cell to <b>$B$3</b>.','Run Goal Seek. With B1 and B2 fixed, the required B3 value is <b>108</b>. Decline the replacement, because a mark above 100 is outside the exercise\'s allowed range.'])
box('Interpretation','A mathematical solution may not be a valid real-world answer. With 78 and 84 fixed, even 100 in IT gives only 262 out of 300.')
sub('Part B: Prepare the marksheet for printing')
steps(['Return to Marks. Select the complete table and use <b>Format &gt; Print Ranges &gt; Define</b>.','Open <b>Format &gt; Page Style &gt; Sheet</b>. Choose suitable scaling, check the preview and export or print the marksheet.'])
shot('calc_046.png','Page Style, Sheet tab, with printing and scaling controls.',160)
para('<b>Expected result:</b> A sensible interpretation of Goal Seek and a readable marksheet whose columns fit on the printed page.',10.5,15)

page('PROJECT','Conclusion')
para('This project explains how LibreOffice Writer, Base and Calc can support common school tasks. Although each application works with information differently, they can be used together to prepare clear and useful work.',12,19,20)
table([['Application','Skills covered','Example output'],['Writer','Formatting, styles, contents, tables, pictures, editing and PDF export','School activity report'],['Base','Database creation, fields, keys, records, queries, forms and reports','Student database and high-scorer report'],['Calc','Formulas, functions, references, sorting, filtering, charts and Goal Seek','Marksheet and column chart']],[80,270,CW-350],10.5)
sub('What the project demonstrates')
para('A well-formatted document is easier to read. A database makes it easier to organise and retrieve records. A spreadsheet reduces repeated arithmetic and helps explain results with charts.')
para('The practical examples also show why checking matters: database keys must be unique, formulas must refer to the correct cells, percentage formats must be used correctly, and calculated answers must make sense in the situation.')
sub('Short viva questions')
steps(['What is the difference between a Writer style and direct formatting?','Why should a database table have a primary key?','How do a query, a form and a report differ?','What is the difference between B2 and $B$2?','Why is the Goal Seek result of 108 unsuitable in this exercise?'])
box('Final learning','Select the right application, organise information carefully, verify the result and save an editable copy before preparing final output.')

page('PROJECT','Bibliography')
para('Official documentation used to check interface details and practical commands. Accessed 12 October 2026. The following titles are clickable in the PDF.',10,14,16,MUTED)
refs=[
 ('1. Getting Started Guide 24.8 - Writer','https://books.libreoffice.org/en/GS248/GS24802-GettingStartedWithWriter.html'),
 ('2. Getting Started Guide 24.8 - Base','https://books.libreoffice.org/en/GS248/GS24808-GettingStartedWithBase.html'),
 ('3. Getting Started Guide 24.8 - Calc','https://books.libreoffice.org/en/GS248/GS24803-GettingStartedWithCalc.html'),
 ('4. Calc Guide 24.2 - Creating Charts and Graphs','https://books.libreoffice.org/en/CG24/CG2403-ChartsAndGraphs.html'),
 ('5. LibreOffice Help - Creating a Table of Contents','https://help.libreoffice.org/latest/en-US/text/swriter/guide/indices_toc.html'),
 ('6. LibreOffice Help - Mail Merge Wizard','https://help.libreoffice.org/latest/en-US/text/swriter/01/mailmerge00.html'),
 ('7. LibreOffice Help - Goal Seek','https://help.libreoffice.org/latest/en-US/text/scalc/01/06040000.html')]
for label,url in refs:
 para(f'<link href="{url}" color="#2465a4"><u>{label}</u></link>',10.5,16,4)
 # Break only at URL separators so the full address stays readable in print.
 shown=url.replace('/', '/<wbr/>').replace('-', '-<wbr/>')
 para(shown,8.3,11.5,13,MUTED)
sub('Picture credits and reuse')
para('All application screenshots are reproduced from the guides listed in references 1-4, by the LibreOffice Documentation Team, copyright 2024. They are used under the <link href="https://creativecommons.org/licenses/by/4.0/" color="#2465a4"><u>Creative Commons Attribution 4.0 licence</u></link>. Screenshots have been resized to fit these pages; their original interface labels and example data have been retained.',9.5,14)
para('Writer screenshots: reference 1. Base screenshots: reference 2. Calc screenshots: reference 3. Chart Wizard screenshot: reference 4. The school exercises, sample names, marks, tables and sample chart were prepared for this project.',9.5,14)
box('About the illustrations','Reference screenshots explain what a window or dialog looks like. They are not evidence of practical work performed by the student. Menu wording and appearance can vary with the installed version and selected interface.')

c.save()
r=PdfReader(str(pdf))
assert len(r.pages)==24, len(r.pages)
texts=[p.extract_text() or '' for p in r.pages]
assert all(str(i) in texts[i-1] for i in range(2,25))
assert 'Bonafide Certificate' in texts[1]
assert 'Writer: Introduction' in texts[5]
assert 'Base: Introduction' in texts[10]
assert 'Calc: Introduction' in texts[16]
assert sum(len(p.images) for p in r.pages)>=15
print('Created:',pdf)
print('Pages:',len(r.pages),'Images:',sum(len(p.images) for p in r.pages),'Words:',sum(len(t.split()) for t in texts))
for i,p in enumerate(r.pages,1): print(i,(p.extract_text() or '').splitlines()[2:4])
