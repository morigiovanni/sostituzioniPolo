import gspread
import streamlit as st
from oauth2client.service_account import ServiceAccountCredentials

from ast import match_case
import pandas as pd
import numpy as np
creds_dict = st.secrets["gcp_service_account"]
classiSede=["2C-AFM","2B-AFM","2D-AFM","4L-RIM","4L-AFM", "3G-SIA","3F-SIA", "5F-RIM","5F-SIA","4L-AFM, 4L-RIM","4F-SIA","5F-RIM, 5F-SIA","1C-AFM","1B-AFM","3L-RIM"]
offset=[0,0,0,0,0,0]
initOre=[4,17,30,43,56,0]
classe=2
doce=3
supp=4
docentiAssenti=[]
listaCelledaAggiornare=[]
scope = ['https://spreadsheets.google.com/feeds',
             'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
#creds = ServiceAccountCredentials.from_json_keyfile_name('progettoorariopython-1dcdbcf2aabc.json', scope)
client = gspread.authorize(creds)


opzioniAgg=["N","S"]
agg=st.pills("Aggiornamento?",opzioniAgg,default="S" )


@st.cache_data(ttl=600)
def carica_dati():

  sheet1= client.open_by_key('1Btwyv-MKjBhODUHwdlCtS8faF5uR7Sl2Che2PVUZaCQ')
  sh1=sheet1.get_worksheet(0)
  data = sh1.get_all_records()
  return pd.DataFrame(data)

sheet = client.open_by_key('1WtRNOWubgWlJhnyc2YzYGb9IJpe-Zne7w8vWC6E7Al0')
sh=sheet.get_worksheet(1)
orario=carica_dati()
orario.replace("",np.nan,inplace=True)
giorno="Lun"

opzioniGio=["Lun","Mar","Mer","Gio","Ven","Sab"]

giorno=st.pills("Giorno?", opzioniGio)

if ((agg=='s')or(agg=='S')):
  for i in range (1,6):
    offset[i-1]=int(sh.cell(i,8).value)
else:
  sh.batch_clear(["B4:D68"])
  sh.batch_clear(["F4:G68"])
  sh.batch_clear(["H1:H5"])
  for i in range (1,6):
    cell=gspread.Cell(i,8,offset[i-1])
    listaCelledaAggiornare.append(cell)
  sh.update_cells(listaCelledaAggiornare)
  listaCelledaAggiornare=[]
  for ora in range(1, 6):

    periodo=giorno+"._"+str(ora)+"_2"
    righe_non_vuote = orario[['DOCENTE', periodo]].dropna()
    cell=gspread.Cell((initOre[ora-1]),6,righe_non_vuote[righe_non_vuote[periodo]=="DISP_SUCC"].loc[:,'DOCENTE'].to_string(index=False))
    listaCelledaAggiornare.append(cell)
    cell1=gspread.Cell((initOre[ora-1]),7,righe_non_vuote[righe_non_vuote[periodo]=="DISP_SEDE"].loc[:,'DOCENTE'].to_string(index=False))
    listaCelledaAggiornare.append(cell1)
  sh.update_cells(listaCelledaAggiornare)
    #sh.update_cell((initOre[ora-1]),7,righe_non_vuote[righe_non_vuote[periodo]=="DISP_SEDE"].loc[:,'DOCENTE'].to_string(index=False))
    #time.sleep(1)
elenco_docenti=orario['DOCENTE'].tolist()
#docA=st.text_input('Chi è asssente oggi?')
#while (docA != '0'):
#  docentiAssenti.append(docA)
#  docA=st.text_st.text_input('Chi è asssente oggi?')
####################################################################################
PGiornaliero, POrario = st.columns(2)
with PGiornaliero:
  listaCelledaAggiornare.clear()
  st.subheader("Assenza giornaliera")
  st.write()
  docentiAssenti = st.multiselect(
    "Seleziona i docenti assenti:",
    options=elenco_docenti
)

# 3. Pulsante per avviare l'azione
  if st.button("Calcola Sostituzioni Giornaliere"):
    if docentiAssenti:
        st.write("Sto calcolando le sostituzioni per:")
        st.write(docentiAssenti)
        for docente in docentiAssenti:
          for ora in range(1,6):
            periodo=giorno+"._"+str(ora)+"_2"
            supplente=0
            st.write(ora)
            righe_non_vuote = orario[['DOCENTE', periodo]].dropna()
            if (righe_non_vuote[righe_non_vuote['DOCENTE']==docente].empty):
                st.write()
            if not(righe_non_vuote[righe_non_vuote['DOCENTE']==docente].empty):
      #sh.update_cell(,righe_non_vuote[righe_non_vuote['DOCENTE']==docente].iloc[0,1])
                cla=righe_non_vuote[righe_non_vuote['DOCENTE']==docente].iloc[0,1]
                indice=righe_non_vuote[righe_non_vuote['DOCENTE']==docente].index[0]
                st.write(righe_non_vuote[righe_non_vuote['DOCENTE']==docente].iloc[0,1])
                st.write(righe_non_vuote[righe_non_vuote['DOCENTE']==docente].iloc[0,0])
                if ((cla!="DISP_SEDE") and (cla!="DISP_SUCC")):
                    cell=gspread.Cell((initOre[ora-1]+offset[ora-1]),classe,righe_non_vuote[righe_non_vuote['DOCENTE']==docente].iloc[0,1])
                    listaCelledaAggiornare.append(cell)
                    cell=gspread.Cell((initOre[ora-1]+offset[ora-1]),doce,righe_non_vuote[righe_non_vuote['DOCENTE']==docente].iloc[0,0])
                    listaCelledaAggiornare.append(cell)
                    #sh.update_cell((initOre[ora-1]+offset[ora-1]),classe,righe_non_vuote[righe_non_vuote['DOCENTE']==docente].iloc[0,1])
                    #sh.update_cell((initOre[ora-1]+offset[ora-1]),doce,righe_non_vuote[righe_non_vuote['DOCENTE']==docente].iloc[0,0])
                    righe_non_vuote=righe_non_vuote.drop(index=indice)
                    for compresente in righe_non_vuote['DOCENTE']:
                        if not(righe_non_vuote[righe_non_vuote['DOCENTE']==compresente].empty):
                            if((righe_non_vuote[righe_non_vuote['DOCENTE']==compresente].iloc[0,1]==cla)and supplente==0):
                                if (cla!=''):
                                  st.write(compresente)
                                  cell=gspread.Cell((initOre[ora-1]+offset[ora-1]),supp,compresente)
                                  listaCelledaAggiornare.append(cell)
                                  #cell=gspread.Cell((initOre[ora-1]+offset[ora-1]),supp,righe_non_vuote[righe_non_vuote['DOCENTE']==compresente].iloc[0,0])
                                  #sh.update_cell((initOre[ora-1]+offset[ora-1]),supp,righe_non_vuote[righe_non_vuote['DOCENTE']==compresente].iloc[0,0])
                                supplente=1
                    if ((cla in classiSede) and (supplente==0)):
                        cell=gspread.Cell((initOre[ora-1]+offset[ora-1]),doce+1, "SEDE")
                        listaCelledaAggiornare.append(cell)
                        #sh.update_cell((initOre[ora-1]+offset[ora-1]),doce+1, "SEDE")
                    elif (not (cla in classiSede) and (supplente==0)):
                        cell=gspread.Cell((initOre[ora-1]+offset[ora-1]),doce+1, "MORO")
                        listaCelledaAggiornare.append(cell)
                        #sh.update_cell((initOre[ora-1]+offset[ora-1]),doce+1, "MORO")
        #st.write(indice)
                    offset[ora-1]=offset[ora-1]+1
                    cell=gspread.Cell(ora,8,offset[ora-1])
                    listaCelledaAggiornare.append(cell)
                    #sh.update_cell(ora,8,offset[ora-1])
        #time.sleep(1)
        if len(listaCelledaAggiornare)>0:
          sh.update_cells(listaCelledaAggiornare)
    else:
        st.warning("Non hai selezionato nessun docente.")
#ora= int (st.text_input('Ora? '))
with POrario:
  listaCelledaAggiornare.clear()
  
  st.subheader("Assenza oraria")
  st.write()
  
  docente = st.selectbox(
    "Seleziona il docente assente:",
    options=elenco_docenti
    )
  
  options=[1,2,3,4,5]
  OreAssenza=st.pills("Ore di assenza", options, selection_mode="multi")
  if st.button("Calcola Sostituzioni Orarie"):
    for ora in OreAssenza:
      periodo=giorno+"._"+str(ora)+"_2"
      supplente=0
      st.write(ora)
      righe_non_vuote = orario[['DOCENTE', periodo]].dropna()
      if (righe_non_vuote[righe_non_vuote['DOCENTE']==docente].empty):
        st.write()
      if not(righe_non_vuote[righe_non_vuote['DOCENTE']==docente].empty):
      #sh.update_cell(,righe_non_vuote[righe_non_vuote['DOCENTE']==docente].iloc[0,1])
        cla=righe_non_vuote[righe_non_vuote['DOCENTE']==docente].iloc[0,1]
        indice=righe_non_vuote[righe_non_vuote['DOCENTE']==docente].index[0]
        st.write(righe_non_vuote[righe_non_vuote['DOCENTE']==docente].iloc[0,1])
        st.write(righe_non_vuote[righe_non_vuote['DOCENTE']==docente].iloc[0,0])
        if ((cla!="D. SEDE") and (cla!="D. A. MORO")):
          cell=gspread.Cell((initOre[ora-1]+offset[ora-1]),classe,righe_non_vuote[righe_non_vuote['DOCENTE']==docente].iloc[0,1])
          listaCelledaAggiornare.append(cell)
        #sh.update_cell((initOre[ora-1]+offset[ora-1]),classe,righe_non_vuote[righe_non_vuote['DOCENTE']==docente].iloc[0,1])
          cell=gspread.Cell((initOre[ora-1]+offset[ora-1]),doce,righe_non_vuote[righe_non_vuote['DOCENTE']==docente].iloc[0,0])
          listaCelledaAggiornare.append(cell)
        #sh.update_cell((initOre[ora-1]+offset[ora-1]),doce,righe_non_vuote[righe_non_vuote['DOCENTE']==docente].iloc[0,0])
          righe_non_vuote=righe_non_vuote.drop(index=indice)
          for compresente in righe_non_vuote['DOCENTE']:
            if not(righe_non_vuote[righe_non_vuote['DOCENTE']==compresente].empty):
              if((righe_non_vuote[righe_non_vuote['DOCENTE']==compresente].iloc[0,1]==cla)and supplente==0):
                print(compresente)
                cell=gspread.Cell((initOre[ora-1]+offset[ora-1]),supp,compresente)
                listaCelledaAggiornare.append(cell)
              #sh.update_cell((initOre[ora-1]+offset[ora-1]),supp,righe_non_vuote[righe_non_vuote['DOCENTE']==compresente].iloc[0,0])
                supplente=1
          if ((cla in classiSede) and (supplente==0)):
            cell=gspread.Cell((initOre[ora-1]+offset[ora-1]),doce+1, "SEDE")
            listaCelledaAggiornare.append(cell)
          #sh.update_cell((initOre[ora-1]+offset[ora-1]),doce+1, "SEDE")
          elif (not (cla in classiSede) and (supplente==0)):
            cell=gspread.Cell((initOre[ora-1]+offset[ora-1]),doce+1, "MORO")
            listaCelledaAggiornare.append(cell)
          #sh.update_cell((initOre[ora-1]+offset[ora-1]),doce+1, "MORO")
        #print(indice)
          offset[ora-1]=offset[ora-1]+1
          cell=gspread.Cell(ora,8,offset[ora-1])
          listaCelledaAggiornare.append(cell)
        #sh.update_cell(ora,8,offset[ora-1])
    if len(listaCelledaAggiornare)>0:
      sh.update_cells(listaCelledaAggiornare)
