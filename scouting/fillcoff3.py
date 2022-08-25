import awkward as ak
from coffea import hist, processor, nanoevents
import uproot
from coffea.nanoevents import NanoEventsFactory, BaseSchema
import matplotlib.pyplot as plt
import mplhep as hep
import numpy as np
import uproot
import pickle
import time
from distributed import Client
#from lpcjobqueue import LPCCondorCluster
import sys
import vector
from math import pi
import dask
import fastjet

from coffea.jetmet_tools import FactorizedJetCorrector, JetCorrectionUncertainty
from coffea.jetmet_tools import JECStack, CorrectedJetsFactory
from coffea.lookup_tools import extractor

#from coffea.analysis_tools import Weights


# register our candidate behaviors
from coffea.nanoevents.methods import candidate
ak.behavior.update(candidate.behavior)


########SYSTEMATICS
trigSystematics = 0 #0: nominal, 1: up err, 2: down err
AK4sys = 0 #o: nominal, 1: err up, 2 err dowm
AK15sys = 0 #o: nominal, 1: err up, 2 err dowm
killTrks = False
PUSystematics = 0 #0: nominal, 1: up err, 2: down err

########################
eventDisplay_knob= False
redoISRRM = True

def pileup_weight(era,puarray,systematics=0):
    if era == 2018:
        f_MC = uproot.open("systematics/pileup/mcPileupUL2018.root")
        f_data = uproot.open("systematics/pileup/PileupHistogram-UL2018-100bins_withVar.root")
    elif era == 2017:
        f_MC = uproot.open("systematics/pileup/mcPileupUL2017.root")
        f_data = uproot.open("systematics/pileup/PileupHistogram-UL2017-100bins_withVar.root")
    elif era == 2016:
        f_MC = uproot.open("systematics/pileup/mcPileupUL2016.root")
        f_data = uproot.open("systematics/pileup/PileupHistogram-UL2016-100bins_withVar.root")
    else:
        print('no pileup weights because no year was selected for function pileup_weight')

    hist_MC = f_MC['pu_mc'].to_numpy()
    #Normalize the data distribution
    hist_data = f_data['pileup'].to_numpy()
    hist_data[0].sum()
    norm_data = hist_data[0]/hist_data[0].sum()
    weights = np.divide(norm_data, hist_MC[0], out=np.ones_like(norm_data), where=hist_MC[0]!=0)

    #The plus version of the pileup
    hist_data_plus = f_data['pileup_plus'].to_numpy()
    hist_data_plus[0].sum()
    norm_data_plus = hist_data_plus[0]/hist_data_plus[0].sum()
    weights_plus = np.divide(norm_data_plus, hist_MC[0], out=np.ones_like(norm_data_plus), where=hist_MC[0]!=0)

    #The minus version of the pileup
    hist_data_minus = f_data['pileup_minus'].to_numpy()
    hist_data_minus[0].sum()
    norm_data_minus = hist_data_minus[0]/hist_data_minus[0].sum()
    weights_minus = np.divide(norm_data_minus, hist_MC[0], out=np.ones_like(norm_data_minus), where=hist_MC[0]!=0)
    print("PU: ",weights)
    if systematics==0:
      return np.take(weights,puarray)
    elif systematics==1:
      return np.take(weights_plus,puarray)
    elif systematics==2:
      return np.take(weights_minus,puarray)
    else:
      return np.take(weights,puarray)

def gettrigweights(htarray,systematics=0):
    #flats = ak.flatten(htarray).to_numpy()
    bins, trigwgts, wgterr = np.loadtxt("systematics/triggers/trigger_systematics.txt", delimiter=",")
    #bins =np.insert(bins,0,0)
    htbin = np.digitize(htarray,bins)
    trigwgts =np.insert(trigwgts,0,0)
    wgterr =np.insert(wgterr,0,0)
    scaleFactorNom = np.take(trigwgts,htbin)
    scaleFactorErr = np.take(wgterr,htbin)
    if systematics==1:
       scaleFactor = scaleFactorNom + scaleFactorErr
    elif systematics==2:
       scaleFactor = scaleFactorNom - scaleFactorErr
    else:
       scaleFactor = scaleFactorNom
    #print("ht: ",htarray)
    #print("bins: ",bins)
    #print("digi: ",htbin)
    #print("trigs: ",trigwgts)
    #print("trigwgt: ",np.take(trigwgts,htbin))
    return scaleFactor

def jetAngularities(jet, candidates,R0=1.5):
        dR = candidates.deltaR(jet)
        inv = 1/jet.pt
        girth = ak.sum(inv*candidates.pt*dR/(R0),axis=1) 
        pt_dispersion = ak.sum(inv*inv*candidates.pt*candidates.pt,axis=1)
        lesHouches = ak.sum(inv*candidates.pt*np.sqrt(dR/R0),axis=1)
        thrust = ak.sum(inv*candidates.pt*(dR/R0)*(dR/R0),axis=1)
        return [girth,pt_dispersion,lesHouches,thrust]
def nSubjettiness( n, jet, candidates, R0=1.5):
        print("Test 1")
        definition = fastjet.JetDefinition(fastjet.antikt_algorithm, R0/np.sqrt(n))
        print("Test 2")
        cluster = fastjet.ClusterSequence(candidates, definition)
        print("Test 3")
        #subjets = ak.with_name(cluster.inclusive_jets(),"Momentum4D")
        subjets = ak.with_name(cluster.exclusive_jets(n_jets=n),"Momentum4D")
        print("Test 4")
        d0 = ak.sum(subjets.pt*R0,axis=1)
        dR = ak.min(candidates.deltaR(subjets),axis=1)
        numerator = ak.sum(candidates.pt*dR,axis=1)
        print("Test 5")
        return numerator/d0

def get_dr_ring(dr, phi_c=0, eta_c=0, n_points=600):
    deta = np.linspace(-dr, +dr, n_points)
    dphi = np.sqrt(dr**2 - np.square(deta))
    deta = eta_c+np.concatenate((deta, deta[::-1]))
    dphi = phi_c+np.concatenate((dphi, -dphi[::-1]))
    return dphi, deta

def plot_display(ievt,ht,particles,bparticles,suepjet,isrjet,bisrjet,sphericity,nbtracks,isrtracks):
    fig = plt.figure(figsize=(8,8))
    ax = plt.gca()

    ax.set_xlim(-pi,pi)
    ax.set_ylim(-2.5,2.5)
    ax.set_xlabel(r'$\phi$', fontsize=18)
    ax.set_ylabel(r'$\eta$', fontsize=18)
    ax.tick_params(axis='both', which='major', labelsize=12)

    ax.scatter(particles.phi, particles.eta, s=2*particles.pt, c='xkcd:blue', marker='o',label="ID tracks: %d"%len(particles))

    phi_s, eta_s = get_dr_ring(1.5,suepjet.phi, suepjet.eta)
    phi_s = phi_s[1:]
    eta_s = eta_s[1:]
    ax.plot(phi_s[phi_s> pi] - 2*pi, eta_s[phi_s>pi], color='xkcd:green',linestyle='--')
    ax.plot(phi_s[phi_s< -pi] + 2*pi, eta_s[phi_s<-pi], color='xkcd:green',linestyle='--')
    ax.plot(phi_s[phi_s< pi], eta_s[phi_s<pi], color='xkcd:green',linestyle='--',label="SUEP Jet: %d [GeV]; %s tracks"%(suepjet.pt,len(nbtracks)))
    phi_i, eta_i = get_dr_ring(1.5,isrjet.phi, isrjet.eta)
    phi_i = phi_i[1:]
    eta_i = eta_i[1:]
    ax.plot(phi_i[phi_i> pi] - 2*pi, eta_i[phi_i>pi], color='xkcd:red',linestyle='--')
    ax.plot(phi_i[phi_i< -pi] + 2*pi, eta_i[phi_i<-pi], color='xkcd:red',linestyle='--')
    ax.plot(phi_i[phi_i< pi], eta_i[phi_i<pi], color='xkcd:red',linestyle='--',label="ISR Jet: %d [GeV]; %s tracks"%(isrjet.pt,len(isrtracks)))

    plt.legend(title='Event (after selection): %d\n Ht: %d'%(ievt,ht))
    hep.cms.label('',data=False,lumi=59.69,year=2018,loc=2)

    fig.savefig("Displays/nonboosted_%s%s.pdf"%(fin,ievt))
    plt.close()


    fig = plt.figure(figsize=(8,8))
    ax = plt.gca()

    ax.set_xlim(-pi,pi)
    ax.set_ylim(-2.5,2.5)
    ax.set_xlabel(r'$\phi$', fontsize=18)
    ax.set_ylabel(r'$\eta$', fontsize=18)
    ax.tick_params(axis='both', which='major', labelsize=12)
    ax.scatter(bparticles.phi, bparticles.eta, s=2*bparticles.pt, c='xkcd:magenta', marker='o',label="Boosted ISR tracks:%s"%(len(isrtracks)))
    ax.scatter(nbtracks.phi, nbtracks.eta, s=2*nbtracks.pt, c='xkcd:blue', marker='o',label="Boosted SUEP tracks:%s"%len(nbtracks))
    phi_ib, eta_ib = get_dr_ring(1.5,bisrjet.phi, bisrjet.eta)
    phi_ib = phi_ib[1:]
    eta_ib = eta_ib[1:]
    ax.plot(phi_ib[phi_ib> pi] - 2*pi, eta_ib[phi_ib>pi], color='xkcd:orange',linestyle='--')
    ax.plot(phi_ib[phi_ib< -pi] + 2*pi, eta_ib[phi_ib<-pi], color='xkcd:orange',linestyle='--')
    ax.plot(phi_ib[phi_ib< pi], eta_ib[phi_ib<pi], color='xkcd:orange',linestyle='--',label="Boosted ISR Jet: %d [GeV]"%isrjet.pt)

    #topline = bisrjet.phi+1.6
    #botline = bisrjet.phi-1.6
    #if topline > pi:
    #  topline = topline - 2*pi
    #if botline < -pi:
    #  botline = botline + 2*pi
    #ax.axvline(x=topline)
    #ax.axvline(x=botline)

    plt.legend(title='Event: %d\n Ht: %d SUEP Jet pt: %d\n Boosted Sphericity: %.2f'%(ievt,ht,suepjet.pt,sphericity))
    hep.cms.label('',data=False,lumi=59.69,year=2018,loc=2)

    fig.savefig("Displays/boosted_%s%s.pdf"%(fin,ievt))
    plt.close()
    


def sphericity(self, particles, r):
    norm = ak.sum(particles.p ** r, axis=1, keepdims=True)
    s = np.array([[
                   ak.sum(particles.px * particles.px * particles.p ** (r-2.0), axis=1 ,keepdims=True)/norm,
                   ak.sum(particles.px * particles.py * particles.p ** (r-2.0), axis=1 ,keepdims=True)/norm,
                   ak.sum(particles.px * particles.pz * particles.p ** (r-2.0), axis=1 ,keepdims=True)/norm
                  ],
                  [
                   ak.sum(particles.py * particles.px * particles.p ** (r-2.0), axis=1 ,keepdims=True)/norm,
                   ak.sum(particles.py * particles.py * particles.p ** (r-2.0), axis=1 ,keepdims=True)/norm,
                   ak.sum(particles.py * particles.pz * particles.p ** (r-2.0), axis=1 ,keepdims=True)/norm
                  ],
                  [
                   ak.sum(particles.pz * particles.px * particles.p ** (r-2.0), axis=1 ,keepdims=True)/norm,
                   ak.sum(particles.pz * particles.py * particles.p ** (r-2.0), axis=1 ,keepdims=True)/norm,
                   ak.sum(particles.pz * particles.pz * particles.p ** (r-2.0), axis=1 ,keepdims=True)/norm
                  ]])
    s = np.squeeze(np.moveaxis(s, 2, 0),axis=3)
    evals = np.sort(np.linalg.eigvalsh(s))
    return evals

def packtrig(output,vals,var):
        output["trigdist_%s"%(var)].fill(cut="Cut 0: No cut", v1=vals[0][var])#,weight=vals[0]["wgt"])
        output["trigdist_%s"%(var)].fill(cut="Cut 1: Ref Trig", v1=vals[1][var])#,weight=vals[1]["wgt"]) 
        output["trigdist_%s"%(var)].fill(cut="Cut 2: HT Trig noRef", v1=vals[2][var])#,weight=vals[2]["wgt"]) 
        output["trigdist_%s"%(var)].fill(cut="Cut 3: HT Trig Ref", v1=vals[3][var])#,weight=vals[3]["wgt"]) 
        return output
def packsingledist(output,vals,var,wgt=True):
        if wgt:
          output["dist_%s"%(var)].fill(cut="cut 0:No cut", v1=vals[var],weight=vals["wgt"])
        else:
          output["dist_%s"%(var)].fill(cut="cut 0:No cut", v1=vals[var])
        return output
def packdist(output,vals,var,prefix=""):
        output["dist_%s%s"%(prefix,var)].fill(cut="cut 0:No cut", v1=vals[0][var],weight=vals[0]["wgt"])
        output["dist_%s%s"%(prefix,var)].fill(cut="cut 1:HT Trig", v1=vals[1][var],weight=vals[1]["wgt"]) 
        output["dist_%s%s"%(prefix,var)].fill(cut="cut 2:Ht>=600", v1=vals[2][var],weight=vals[2]["wgt"])
        output["dist_%s%s"%(prefix,var)].fill(cut="cut 3:fj>=2", v1=vals[3][var],weight=vals[3]["wgt"])
        if("PFcand_n" in var):
          output["dist_%s%s"%(prefix,var)].fill(cut="cut 4:eventBoosted Sphericity >=0.6", v1=vals[4][var],weight=vals[4]["wgt"])
        else:
          output["dist_%s%s"%(prefix,var)].fill(cut="cut 4:nPFcand(SUEP)>=70", v1=vals[4][var],weight=vals[4]["wgt"]) 
        if(len(vals)>=6):
          output["dist_%s%s"%(prefix,var)].fill(cut="cut 5:eventBoosted Sphericity > 0.7", v1=vals[5][var],weight=vals[5]["wgt"]) 
          #output["dist_%s"%(var)].fill(cut="cut 3:Pre + nPVs < 30", v1=vals[5][var]) 
          #output["dist_%s"%(var)].fill(cut="cut 4:Pre + nPVs >=30", v1=vals[6][var]) 
      
        #output["dist_%s"%(var)].fill(cut="cut 4:FJ nPFCand>=80", v1=vals[4][var]) 
        return output
def packtrkFKID(output,vals,var,var2,prefix=""):
        output["dist_trkIDFK_%s%s"%(prefix,var)].fill(cut="cut 0:Preselection",          v1=ak.flatten(vals[0][var]), v2=ak.flatten(vals[0][var2]))
        output["dist_trkIDFK_%s%s"%(prefix,var)].fill(cut="cut 1: |eta| < 2.4",          v1=ak.flatten(vals[1][var]), v2=ak.flatten(vals[1][var2]))
        output["dist_trkIDFK_%s%s"%(prefix,var)].fill(cut="cut 2: q != 0",               v1=ak.flatten(vals[2][var]), v2=ak.flatten(vals[2][var2]))
        output["dist_trkIDFK_%s%s"%(prefix,var)].fill(cut="cut 3: PV = 0",               v1=ak.flatten(vals[3][var]), v2=ak.flatten(vals[3][var2]))
        output["dist_trkIDFK_%s%s"%(prefix,var)].fill(cut="cut 4: PFcand_pt > 0.5",      v1=ak.flatten(vals[4][var]), v2=ak.flatten(vals[4][var2]))
        output["dist_trkIDFK_%s%s"%(prefix,var)].fill(cut="cut 5: PFcand_pt > 0.6",      v1=ak.flatten(vals[5][var]), v2=ak.flatten(vals[5][var2]))
        output["dist_trkIDFK_%s%s"%(prefix,var)].fill(cut="cut 6: PFcand_pt > 0.7",      v1=ak.flatten(vals[6][var]), v2=ak.flatten(vals[6][var2]))
        output["dist_trkIDFK_%s%s"%(prefix,var)].fill(cut="cut 7: PFcand_pt > 0.75",     v1=ak.flatten(vals[7][var]), v2=ak.flatten(vals[7][var2]))
        output["dist_trkIDFK_%s%s"%(prefix,var)].fill(cut="cut 8: PFcand_pt > 0.8",      v1=ak.flatten(vals[8][var]), v2=ak.flatten(vals[8][var2]))
        output["dist_trkIDFK_%s%s"%(prefix,var)].fill(cut="cut 9: PFcand_pt > 0.9",      v1=ak.flatten(vals[9][var]), v2=ak.flatten(vals[9][var2]))
        output["dist_trkIDFK_%s%s"%(prefix,var)].fill(cut="cut 10: PFcand_pt > 1.0",     v1=ak.flatten(vals[10][var]), v2=ak.flatten(vals[10][var2]))
        return output
def packtrkID(output,vals,var,var2,var3,prefix=""):
        output["dist_trkID_%s%s"%(prefix,var)].fill(cut="cut 0:Preselection",           v1=ak.flatten(vals[0][var]), v2=ak.flatten(vals[0][var2]), v3=ak.flatten(vals[0][var3]))
        output["dist_trkID_%s%s"%(prefix,var)].fill(cut="cut 1: PFcand_pt > 0.5",       v1=ak.flatten(vals[1][var]), v2=ak.flatten(vals[1][var2]), v3=ak.flatten(vals[1][var3]))
        output["dist_trkID_%s%s"%(prefix,var)].fill(cut="cut 2: PFcand_pt > 0.6",       v1=ak.flatten(vals[2][var]), v2=ak.flatten(vals[2][var2]), v3=ak.flatten(vals[2][var3]))
        output["dist_trkID_%s%s"%(prefix,var)].fill(cut="cut 3: PFcand_pt > 0.7",       v1=ak.flatten(vals[3][var]), v2=ak.flatten(vals[3][var2]), v3=ak.flatten(vals[3][var3]))
        output["dist_trkID_%s%s"%(prefix,var)].fill(cut="cut 4: PFcand_pt > 0.75",      v1=ak.flatten(vals[4][var]), v2=ak.flatten(vals[4][var2]), v3=ak.flatten(vals[4][var3]))
        output["dist_trkID_%s%s"%(prefix,var)].fill(cut="cut 5: PFcand_pt > 0.8",       v1=ak.flatten(vals[5][var]), v2=ak.flatten(vals[5][var2]), v3=ak.flatten(vals[5][var3]))
        output["dist_trkID_%s%s"%(prefix,var)].fill(cut="cut 6: PFcand_pt > 0.9",       v1=ak.flatten(vals[6][var]), v2=ak.flatten(vals[6][var2]), v3=ak.flatten(vals[6][var3]))
        output["dist_trkID_%s%s"%(prefix,var)].fill(cut="cut 7: PFcand_pt > 1.0",       v1=ak.flatten(vals[7][var]), v2=ak.flatten(vals[7][var2]), v3=ak.flatten(vals[7][var3]))
        return output
def packdistflat(output,vals,var,prefix=""):
        output["dist_%s%s"%(prefix,var)].fill(cut="cut 0:No cut",       v1=ak.flatten(vals[0][var]))
        output["dist_%s%s"%(prefix,var)].fill(cut="cut 1:HT Trig",      v1=ak.flatten(vals[1][var])) 
        output["dist_%s%s"%(prefix,var)].fill(cut="cut 2:Ht>=600",      v1=ak.flatten(vals[2][var]))
        output["dist_%s%s"%(prefix,var)].fill(cut="cut 3:fj>=2",        v1=ak.flatten(vals[3][var]))
        output["dist_%s%s"%(prefix,var)].fill(cut="cut 4:nPFCand(SUEP)>=70", v1=ak.flatten(vals[4][var])) 
        #if(len(vals)>=6):
        #  output["dist_%s%s"%(prefix,var)].fill(cut="cut 3:Pre + nPVs < 30", v1=ak.flatten(vals[5][var])) 
        #  output["dist_%s%s"%(prefix,var)].fill(cut="cut 4:Pre + nPVs >=30", v1=ak.flatten(vals[6][var]))
        return output
def packdist_fjn1(output,vals,var):
        output["dist_fjn1_%s"%(var)].fill(cut="cut 0:No cut",       v1=vals[0][var],weight=vals[0]["wgt"])
        output["dist_fjn1_%s"%(var)].fill(cut="cut 1:HT Trig",      v1=vals[1][var],weight=vals[1]["wgt"]) 
        output["dist_fjn1_%s"%(var)].fill(cut="cut 2:Ht>=600",      v1=vals[2][var],weight=vals[2]["wgt"])
        output["dist_fjn1_%s"%(var)].fill(cut="cut 3:nPFCand(SUEP)>=70", v1=vals[3][var],weight=vals[3]["wgt"]) 
        output["dist_fjn1_%s"%(var)].fill(cut="cut 4:BSphericity >=0.7",        v1=vals[4][var],weight=vals[4]["wgt"])
        return output
def packSR(output,vals,var):
        output["SR1_%s_0"%var].fill(axis="axis",       nPFCand=vals[3]["PFcand_ncount75"],eventBoostedSphericity=vals[3]["sphere_%s"%var],weight=vals[3]["wgt"])
        output["SR1_%s_1"%var].fill(axis="axis",       nPFCand=vals[3]["PFcand_ncount75"],eventBoostedSphericity=vals[3]["sphere1_%s"%var],weight=vals[3]["wgt"])
        output["SR1_%s_2"%var].fill(axis="axis",       nPFCand=vals[3]["FatJet_nconst"],eventBoostedSphericity=vals[3]["sphere_%s"%var],weight=vals[3]["wgt"])
        output["SR1_%s_3"%var].fill(axis="axis",       nPFCand=vals[3]["FatJet_nconst"],eventBoostedSphericity=vals[3]["sphere1_%s"%var],weight=vals[3]["wgt"])
        return output
def pack2D(output,vals,var1,var2):
        output["2d_%s_%s"%(var1,var2)].fill(cut="cut 0: No cut",       v1=vals[0][var1],v2=vals[0][var2],weight=vals[0]["wgt"])
        output["2d_%s_%s"%(var1,var2)].fill(cut="cut 1: No cut",       v1=vals[1][var1],v2=vals[1][var2],weight=vals[1]["wgt"])
        output["2d_%s_%s"%(var1,var2)].fill(cut="cut 2: No cut",       v1=vals[2][var1],v2=vals[2][var2],weight=vals[2]["wgt"])
        output["2d_%s_%s"%(var1,var2)].fill(cut="cut 3: No cut",       v1=vals[3][var1],v2=vals[3][var2],weight=vals[3]["wgt"])
        output["2d_%s_%s"%(var1,var2)].fill(cut="cut 4: No cut",       v1=vals[4][var1],v2=vals[4][var2],weight=vals[4]["wgt"])
        return output
def packtrig2D(output,vals,var1,var2):
        output["trig2d_%s_%s"%(var1,var2)].fill(cut="Cut 0: No cut",       v1=vals[0][var1],v2=vals[0][var2],weight=vals[0]["wgt"])
        output["trig2d_%s_%s"%(var1,var2)].fill(cut="Cut 1: Ref Trig",     v1=vals[1][var1],v2=vals[1][var2],weight=vals[1]["wgt"])
        output["trig2d_%s_%s"%(var1,var2)].fill(cut="Cut 2: HT Trig noRef",v1=vals[2][var1],v2=vals[2][var2],weight=vals[2]["wgt"])
        output["trig2d_%s_%s"%(var1,var2)].fill(cut="Cut 3: HT Trig Ref",  v1=vals[3][var1],v2=vals[3][var2],weight=vals[3]["wgt"])
        return output
pt_bins = np.array([0.1,0.2,0.3,0.4,0.5,0.75,1,1.25,1.5,2.0,3,10,20,50])
eta_bins = np.array(range(-250,250,25))/100.
phi_bins = np.array(range(-31,31,5))/10.
class MyProcessor(processor.ProcessorABC):
    def __init__(self):
        self._accumulator = processor.dict_accumulator({
            "sumw": processor.defaultdict_accumulator(float),
            "SR1_isrsuep_0" : hist.Hist(
                      "Events",
                      hist.Cat("axis","Axis"),
                      hist.Bin("nPFCand","nPFCand",300,0,300),
                      hist.Bin("eventBoostedSphericity","eventBoostedSphericity",100,0,1)
            ),
            "SR1_isrsuep_1" : hist.Hist(
                      "Events",
                      hist.Cat("axis","Axis"),
                      hist.Bin("nPFCand","nPFCand",300,0,300),
                      hist.Bin("eventBoostedSphericity","eventBoostedSphericity",100,0,1)
            ),
            "SR1_isrsuep_2" : hist.Hist(
                      "Events",
                      hist.Cat("axis","Axis"),
                      hist.Bin("nPFCand","nPFCand",300,0,300),
                      hist.Bin("eventBoostedSphericity","eventBoostedSphericity",100,0,1)
            ),
            "SR1_isrsuep_3" : hist.Hist(
                      "Events",
                      hist.Cat("axis","Axis"),
                      hist.Bin("nPFCand","nPFCand",300,0,300),
                      hist.Bin("eventBoostedSphericity","eventBoostedSphericity",100,0,1)
            ),
            "SR1_isr_0" : hist.Hist(
                      "Events",
                      hist.Cat("axis","Axis"),
                      hist.Bin("nPFCand","nPFCand",300,0,300),
                      hist.Bin("eventBoostedSphericity","eventBoostedSphericity",100,0,1)
            ),
            "SR1_suep_0" : hist.Hist(
                      "Events",
                      hist.Cat("axis","Axis"),
                      hist.Bin("nPFCand","nPFCand",300,0,300),
                      hist.Bin("eventBoostedSphericity","eventBoostedSphericity",100,0,1)
            ),
            "SR1_16_0" : hist.Hist(
                      "Events",
                      hist.Cat("axis","Axis"),
                      hist.Bin("nPFCand","nPFCand",300,0,300),
                      hist.Bin("eventBoostedSphericity","eventBoostedSphericity",100,0,1)
            ),
            "SR1_10_0" : hist.Hist(
                      "Events",
                      hist.Cat("axis","Axis"),
                      hist.Bin("nPFCand","nPFCand",300,0,300),
                      hist.Bin("eventBoostedSphericity","eventBoostedSphericity",100,0,1)
            ),
            "SR1_8_0" : hist.Hist(
                      "Events",
                      hist.Cat("axis","Axis"),
                      hist.Bin("nPFCand","nPFCand",300,0,300),
                      hist.Bin("eventBoostedSphericity","eventBoostedSphericity",100,0,1)
            ),
            "SR1_4_0" : hist.Hist(
                      "Events",
                      hist.Cat("axis","Axis"),
                      hist.Bin("nPFCand","nPFCand",300,0,300),
                      hist.Bin("eventBoostedSphericity","eventBoostedSphericity",100,0,1)
            ),
            "SR1_isr_1" : hist.Hist(
                      "Events",
                      hist.Cat("axis","Axis"),
                      hist.Bin("nPFCand","nPFCand",300,0,300),
                      hist.Bin("eventBoostedSphericity","eventBoostedSphericity",100,0,1)
            ),
            "SR1_suep_1" : hist.Hist(
                      "Events",
                      hist.Cat("axis","Axis"),
                      hist.Bin("nPFCand","nPFCand",300,0,300),
                      hist.Bin("eventBoostedSphericity","eventBoostedSphericity",100,0,1)
            ),
            "SR1_16_1" : hist.Hist(
                      "Events",
                      hist.Cat("axis","Axis"),
                      hist.Bin("nPFCand","nPFCand",300,0,300),
                      hist.Bin("eventBoostedSphericity","eventBoostedSphericity",100,0,1)
            ),
            "SR1_10_1" : hist.Hist(
                      "Events",
                      hist.Cat("axis","Axis"),
                      hist.Bin("nPFCand","nPFCand",300,0,300),
                      hist.Bin("eventBoostedSphericity","eventBoostedSphericity",100,0,1)
            ),
            "SR1_8_1" : hist.Hist(
                      "Events",
                      hist.Cat("axis","Axis"),
                      hist.Bin("nPFCand","nPFCand",300,0,300),
                      hist.Bin("eventBoostedSphericity","eventBoostedSphericity",100,0,1)
            ),
            "SR1_4_1" : hist.Hist(
                      "Events",
                      hist.Cat("axis","Axis"),
                      hist.Bin("nPFCand","nPFCand",300,0,300),
                      hist.Bin("eventBoostedSphericity","eventBoostedSphericity",100,0,1)
            ),
            "SR1_isr_2" : hist.Hist(
                      "Events",
                      hist.Cat("axis","Axis"),
                      hist.Bin("nPFCand","nPFCand",300,0,300),
                      hist.Bin("eventBoostedSphericity","eventBoostedSphericity",100,0,1)
            ),
            "SR1_suep_2" : hist.Hist(
                      "Events",
                      hist.Cat("axis","Axis"),
                      hist.Bin("nPFCand","nPFCand",300,0,300),
                      hist.Bin("eventBoostedSphericity","eventBoostedSphericity",100,0,1)
            ),
            "SR1_16_2" : hist.Hist(
                      "Events",
                      hist.Cat("axis","Axis"),
                      hist.Bin("nPFCand","nPFCand",300,0,300),
                      hist.Bin("eventBoostedSphericity","eventBoostedSphericity",100,0,1)
            ),
            "SR1_10_2" : hist.Hist(
                      "Events",
                      hist.Cat("axis","Axis"),
                      hist.Bin("nPFCand","nPFCand",300,0,300),
                      hist.Bin("eventBoostedSphericity","eventBoostedSphericity",100,0,1)
            ),
            "SR1_8_2" : hist.Hist(
                      "Events",
                      hist.Cat("axis","Axis"),
                      hist.Bin("nPFCand","nPFCand",300,0,300),
                      hist.Bin("eventBoostedSphericity","eventBoostedSphericity",100,0,1)
            ),
            "SR1_4_2" : hist.Hist(
                      "Events",
                      hist.Cat("axis","Axis"),
                      hist.Bin("nPFCand","nPFCand",300,0,300),
                      hist.Bin("eventBoostedSphericity","eventBoostedSphericity",100,0,1)
            ),
            "SR1_isr_3" : hist.Hist(
                      "Events",
                      hist.Cat("axis","Axis"),
                      hist.Bin("nPFCand","nPFCand",300,0,300),
                      hist.Bin("eventBoostedSphericity","eventBoostedSphericity",100,0,1)
            ),
            "SR1_suep_3" : hist.Hist(
                      "Events",
                      hist.Cat("axis","Axis"),
                      hist.Bin("nPFCand","nPFCand",300,0,300),
                      hist.Bin("eventBoostedSphericity","eventBoostedSphericity",100,0,1)
            ),
            "SR1_16_3" : hist.Hist(
                      "Events",
                      hist.Cat("axis","Axis"),
                      hist.Bin("nPFCand","nPFCand",300,0,300),
                      hist.Bin("eventBoostedSphericity","eventBoostedSphericity",100,0,1)
            ),
            "SR1_10_3" : hist.Hist(
                      "Events",
                      hist.Cat("axis","Axis"),
                      hist.Bin("nPFCand","nPFCand",300,0,300),
                      hist.Bin("eventBoostedSphericity","eventBoostedSphericity",100,0,1)
            ),
            "SR1_8_3" : hist.Hist(
                      "Events",
                      hist.Cat("axis","Axis"),
                      hist.Bin("nPFCand","nPFCand",300,0,300),
                      hist.Bin("eventBoostedSphericity","eventBoostedSphericity",100,0,1)
            ),
            "SR1_4_3" : hist.Hist(
                      "Events",
                      hist.Cat("axis","Axis"),
                      hist.Bin("nPFCand","nPFCand",300,0,300),
                      hist.Bin("eventBoostedSphericity","eventBoostedSphericity",100,0,1)
            ),
            "trigdist_FatJet_nconst": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","SUEP Jet multiplicity",100,0,300)
            ),
            "trigdist_event_sphericity": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","eventSphericity (not boosted)",100,0,1)
            ),
            "trigdist_ht": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","ht",1500,0,1500)
            ),
            "trigdist_ht20": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","ht",1500,0,1500)
            ),
            "trigdist_ht30": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","ht",1500,0,1500)
            ),
            "trigdist_ht40": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","ht",1500,0,1500)
            ),
            "trigdist_ht50": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","ht",1500,0,1500)
            ),
            "trigdist_n_pfMu": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","n_pfMu",15,0,15)
            ),
            "dist_ht": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","Ht",3500,0,3500)
            ),
            "dist_sphere_16": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","Sphereb_16",50,0,1)
            ),
            "dist_sphere1_16": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","Sphere1b_16",50,0,1)
            ),
            "dist_sphere_10": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","Sphereb_10",50,0,1)
            ),
            "dist_sphere1_10": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","Sphere1b_10",50,0,1)
            ),
            "dist_sphere_8": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","Sphereb_8",50,0,1)
            ),
            "dist_sphere1_8": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","Sphere1b_8",50,0,1)
            ),
            "dist_sphere_4": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","Sphereb_4",50,0,1)
            ),
            "dist_sphere1_4": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","Sphere1b_4",50,0,1)
            ),
            "dist_sphere_suep": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","Sphere_suep",50,0,1)
            ),
            "dist_sphere1_suep": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","Sphere1_suep",50,0,1)
            ),
            "dist_sphere_isrsuep": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","Sphere_isr",50,0,1)
            ),
            "dist_sphere1_isrsuep": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","Sphere1_isr",50,0,1)
            ),
            "dist_sphere_isr": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","Sphere_isr",50,0,1)
            ),
            "dist_sphere1_isr": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","Sphere1_isr",50,0,1)
            ),
            "dist_event_sphericity": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","Sphericity",50,0,1)
            ),
            "dist_eventBoosted_sphericity": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","Boosted Sphericity",50,0,1)
            ),
            "dist_cparam_suep": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","cParam_suep",50,0,1)
            ),
            "dist_cparam1_suep": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","cParam1_suep",50,0,1)
            ),
            "dist_dparam_suep": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","dParam_suep",50,0,1)
            ),
            "dist_dparam1_suep": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","dParam1_suep",50,0,1)
            ),
            "dist_aplanarity_suep": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","Aplanarity_suep",50,0,1)
            ),
            "dist_aplanarity1_suep": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","Aplanarity1_suep",50,0,1)
            ),
            "dist_n_pvs": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","nPVs",100,0,100)
            ),
            "dist_nPVs_good0": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","nPVs",100,0,100)
            ),
            "dist_nPVs_good1": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","nPVs",100,0,100)
            ),
            "dist_nPVs_good2": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","nPVs",100,0,100)
            ),
            "dist_nPVs_good3": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","nPVs",100,0,100)
            ),
            "dist_nPVs_good4": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","nPVs",100,0,100)
            ),
            "dist_nPVs_good5": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","nPVs",40,0,40)
            ),
            "dist_nPVs_good6": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","nPVs",40,0,40)
            ),
            "dist_nPVs_good7": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","nPVs",40,0,40)
            ),
            "dist_nPVs_good8": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","nPVs",40,0,40)
            ),
            "dist_nPVs_good9": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","nPVs",40,0,40)
            ),
            "trig2d_ht_FatJet_nconst" : hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","ht",150,0,1500),
                      hist.Bin("v2","Suep jet Track Multiplicity",50,0,300)
            ),
            "trig2d_ht_event_sphericity" : hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","ht",150,0,1500),
                      hist.Bin("v2","Sphericity (unboosted)",50,0,1)
            ),
            #"2d_Vertex_tracksSize_n_pvs" : hist.Hist(
            #          "Events",
            #          hist.Cat("cut","Cutflow"),
            #          hist.Bin("v1","Vertex Tracks Size",200,0,200),
            #          hist.Bin("v2","nPVs",100,0,1)
            #),
            "dist_Vertex_minZ": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","Vertex minZ",100,0,20)
            ),
            "dist_Vertex_valid": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","Vertex Valid",5,0,5)
            ),
            "dist_Vertex_tracksSize0": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","Vertex Track Size 0",200,0,200)
            ),
            "dist_Vertex_tracksSize": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","Vertex Track Size",200,0,200)
            ),
            "dist_Vertex_ndof": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","ndof",20,0,20)
            ),
            "dist_Vertex_chi2": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","Vertex chi2",100,0,5)
            ),
            "dist_Vertex_z": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","Vertex z",100,-50,50)
            ),
            "dist_n_pfcand": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","nPFCand",50,0,300)
            ),
            "dist_PFcand_ncount0": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","nPFCand0",50,0,300)
            ),
            "dist_PFcand_ncount50": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","nPFCand50",50,0,300)
            ),
            "dist_PFcand_ncount60": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","nPFCand60",50,0,300)
            ),
            "dist_PFcand_ncount70": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","nPFCand70",50,0,300)
            ),
            "dist_PFcand_ncount75": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","nPFCand75",50,0,300)
            ),
            "dist_PFcand_ncount80": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","nPFCand80",50,0,300)
            ),
            "dist_PFcand_ncount90": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","nPFCand90",50,0,300)
            ),
            "dist_PFcand_ncount100": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","nPFCand100",50,0,300)
            ),
            "dist_PFcand_ncount150": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","nPFCand150",50,0,300)
            ),
            "dist_PFcand_ncount200": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","nPFCand200",50,0,300)
            ),
            "dist_PFcand_ncount300": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","nPFCand300",50,0,300)
            ),
            "dist_n_jetId": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","nJet",20,0,20)
            ),
            "dist_n_fatjet": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","nFatJet",10,0,10)
            ),
            "dist_Jet_pt": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","Jet_pt",100,0,300)
            ),
            "dist_Jet_eta": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","Jet_eta",eta_bins)
            ),
            "dist_Jet_phi": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","Jet_phi",phi_bins)
            ),
            #"dist_reFatJet_pt": hist.Hist(
            #          "Events",
            #          hist.Cat("cut","Cutflow"),
            #          hist.Bin("v1","reFatJet_pt",100,0,300)
            #),
            #"dist_reFatJet_eta": hist.Hist(
            #          "Events",
            #          hist.Cat("cut","Cutflow"),
            #          hist.Bin("v1","reFatJet_eta",eta_bins)
            #),
            #"dist_reFatJet_phi": hist.Hist(
            #          "Events",
            #          hist.Cat("cut","Cutflow"),
            #          hist.Bin("v1","reFatJet_phi",phi_bins)
            #),
            "dist_FatJet_pt": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","FatJet_pt",100,0,500)
            ),
            "dist_FatJet_eta": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","FatJet_eta",eta_bins)
            ),
            "dist_FatJet_phi": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","FatJet_phi",phi_bins)
            ),
            "dist_fjn1_FatJet_ncount30": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","FatJet_ncount30",11,-0.5,10.5)
            ),
            "dist_fjn1_FatJet_ncount50": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","FatJet_ncount50",11,-0.5,10.5)
            ),
            "dist_fjn1_FatJet_ncount100": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","FatJet_ncount100",11,-0.5,10.5)
            ),
            "dist_fjn1_FatJet_ncount150": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","FatJet_ncount150",11,-0.5,10.5)
            ),
            "dist_fjn1_FatJet_ncount200": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","FatJet_ncount200",11,-0.5,10.5)
            ),
            "dist_fjn1_FatJet_ncount250": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","FatJet_ncount250",11,-0.5,10.5)
            ),
            "dist_fjn1_FatJet_ncount300": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","FatJet_ncount300",11,-0.5,10.5)
            ),
            "dist_FatJet_nconst": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","FatJet_nconst",50,0,300)
            ),
            "dist_FatJet_ncount30": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","FatJet_ncount30",11,-0.5,10.5)
            ),
            "dist_FatJet_ncount50": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","FatJet_ncount50",11,-0.5,10.5)
            ),
            "dist_FatJet_ncount100": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","FatJet_ncount100",11,-0.5,10.5)
            ),
            "dist_FatJet_ncount150": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","FatJet_ncount150",11,-0.5,10.5)
            ),
            "dist_FatJet_ncount200": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","FatJet_ncount200",11,-0.5,10.5)
            ),
            "dist_FatJet_ncount250": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","FatJet_ncount250",11,-0.5,10.5)
            ),
            "dist_FatJet_ncount300": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","FatJet_ncount300",11,-0.5,10.5)
            ),
            "dist_PFcand_pt": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","PFcand_pt",pt_bins)
            ),
            "dist_PFcand_eta": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","PFcand_eta",eta_bins)
            ),
            "dist_PFcand_phi": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","PFcand_phi",phi_bins)
            ),
             ###########TRACKS
            "dist_trkIDFK_PFcand_pt": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","PFcand_pt",pt_bins),
                      hist.Bin("v2","PFcand_dR",100,0,0.3)
            ),
            "dist_trkIDFK_PFcand_eta": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","PFcand_eta",eta_bins),
                      hist.Bin("v2","PFcand_dR",100,0,0.3)
            ),
            "dist_trkIDFK_PFcand_phi": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","PFcand_phi",phi_bins),
                      hist.Bin("v2","PFcand_dR",100,0,0.3)
            ),
            "dist_PFcand_dR": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","PFcand_mindR",50,0,0.3)
            ),
            "dist_PFcand_alldR": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","PFcand_alldR",50,0,0.3)
            ),
            "dist_tau21": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","tau21",100,0,1)
            ),
            "dist_tau32": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","tau32",100,0,1)
            ),
            "dist_SUEP_girth": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","SUEP_girth",100,0,2)
            ),
            "dist_SUEP_ptDispersion": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","SUEP_ptDispersion",100,0,1)
            ),
            "dist_SUEP_lesHouches": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","SUEP_lesHouches",100,0,2)
            ),
            "dist_SUEP_thrust": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","SUEP_thrust",100,0,2)
            ),
            "dist_SUEP_beta": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","SUEP_beta",100,0,5)
            ),
            "dist_SUEP_pt": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","SUEP_pt",50,0,500)
            ),
            "dist_SUEP_eta": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","SUEP_eta",eta_bins)
            ),
            "dist_SUEP_phi": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","SUEP_phi",phi_bins)
            ),
            "dist_SUEP_mass": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","SUEP_mass",100,0,1000)
            ),
            "dist_ISR_beta": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","ISR_beta",100,0,5)
            ),
            "dist_ISR_pt": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","ISR_pt",50,0,500)
            ),
            "dist_ISR_eta": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","ISR_eta",eta_bins)
            ),
            "dist_ISR_phi": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","ISR_phi",phi_bins)
            ),
            "dist_ISR_mass": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","ISR_mass",100,0,1000)
            ),
            "dist_scalar_beta": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","scalar_beta",100,0,5)
            ),
            "dist_scalar_pt": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","scalar_pt",100,0,500)
            ),
            "dist_scalar_eta": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","scalar_eta",eta_bins)
            ),
            "dist_scalar_phi": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","scalar_phi",phi_bins)
            ),
            "dist_scalar_mass": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","scalar_mass",100,0,1000)
            ),
            "dist_res_beta": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","res_pt",50,-5,5)
            ),
            "dist_res_pt": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","res_pt",50,-1000,300)
            ),
            "dist_res_mass": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","res_mass",50,-1000,300)
            ),
            "dist_res_dR": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","res_dR",50,0,6)
            ),
            "dist_res_dEta": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","res_dEta",100,-3,3)
            ),
            "dist_res_dPhi": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","res_dPhi",100,-7,7)
            ),
#            "dist_trkID_genPV_pt": hist.Hist(
#                      "Events",
#                      hist.Cat("cut","Cutflow"),
#                      hist.Bin("v1","gen_pt",pt_bins),
#                      hist.Bin("v2","gen_dR",100,0,0.3)
#            ),
#            "dist_trkID_genPV_eta": hist.Hist(
#                      "Events",
#                      hist.Cat("cut","Cutflow"),
#                      hist.Bin("v1","gen_eta",eta_bins),
#                      hist.Bin("v2","gen_dR",100,0,0.3)
#            ),
#            "dist_trkID_genPV_phi": hist.Hist(
#                      "Events",
#                      hist.Cat("cut","Cutflow"),
#                      hist.Bin("v1","gen_phi",phi_bins),
#                      hist.Bin("v2","gen_dR",100,0,0.3)
#            ),
            "dist_trkID_gen_pt": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","gen_pt",pt_bins),
                      hist.Bin("v2","gen_dR",100,0,0.3),
                      hist.Bin("v3","gen_PV",4,0,4)
            ),
            "dist_trkID_gen_eta": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","gen_eta",eta_bins),
                      hist.Bin("v2","gen_dR",100,0,0.3),
                      hist.Bin("v3","gen_PV",4,0,4)
            ),
            "dist_trkID_gen_phi": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","gen_phi",phi_bins),
                      hist.Bin("v2","gen_dR",100,0,0.3),
                      hist.Bin("v3","gen_PV",4,0,4)
            ),
            "dist_gen_dR": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","gen_dR",50,0,0.3)
            ),
            "dist_gen_pt": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","gen_pt",pt_bins)
            ),
            "dist_gen_eta": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","gen_eta",eta_bins)
            ),
            "dist_gen_phi": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","gen_phi",phi_bins)
            ),
            "dist_gen_PV": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","gen_PV",4,0,4)
            ),
            "dist_gen_PVdZ": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","gen_PVdZ",100,-5,5)
            ),
            "dist_n_pfMu": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","n_pfMuons",15,0,15)
            ),
            "dist_n_pfEl": hist.Hist(
                      "Events",
                      hist.Cat("cut","Cutflow"),
                      hist.Bin("v1","n_pfElectrons",20,0,20)
            ),
        })

    @property
    def accumulator(self):
        return self._accumulator

    def process(self, arrays):
        vector.register_awkward()
        output = self.accumulator.identity()
        dataset = arrays.metadata['dataset']
        output["sumw"][dataset] += len(arrays) # get number of events
        tright = [item[7] for item in arrays["hltResult"]]
        trigmu = [item[5] for item in arrays["hltResult"]] #actually calojet40 reference trigger
        #trigger order:
        #HLT Trigger DST_DoubleMu1_noVtx_CaloScouting_v2
        #HLT Trigger DST_DoubleMu3_noVtx_CaloScouting_Monitoring_v6
        #HLT Trigger DST_DoubleMu3_noVtx_CaloScouting_v6
        #HLT Trigger DST_DoubleMu3_noVtx_Mass10_PFScouting_v3
        #HLT Trigger DST_L1HTT_CaloScouting_PFScouting_v15
        #HLT Trigger DST_CaloJet40_CaloScouting_PFScouting_v15
        #HLT Trigger DST_HT250_CaloScouting_v10
	#HLT Trigger DST_HT410_PFScouting_v16
        ext_ak4 = extractor()
        ext_ak4.add_weight_sets([ #change to correct files
            #"* * systematics/jetscale_corrections/Summer19UL18_V5_MC_L1FastJet_AK4PFchs.txt", #looks to be 0,
            #"* * systematics/jetscale_corrections/Summer19UL18_V5_MC_L1RC_AK4PFchs.txt", #needs area
            "* * systematics/jetscale_corrections/Summer19UL18_V5_MC_L2L3Residual_AK4PFchs.txt",
            "* * systematics/jetscale_corrections/Summer19UL18_V5_MC_L2Residual_AK4PFchs.txt",
            "* * systematics/jetscale_corrections/Summer19UL18_V5_MC_L2Relative_AK4PFchs.jec.txt",
            "* * systematics/jetscale_corrections/Summer19UL18_V5_MC_L3Absolute_AK4PFchs.txt", #looks to be 1, no change
            "* * systematics/jetscale_corrections/Summer19UL18_V5_MC_Uncertainty_AK4PFchs.junc.txt",
            #"* * systematics/jetresolution_corrections/Summer19UL18_JRV2_MC_PtResolution_AK4PFchs.txt",
            #"* * systematics/jetresolution_corrections/Summer19UL18_JRV2_MC_SF_AK4PFchs.txt",
        ])
        ext_ak4.finalize()
        
        jec_stack_names_ak4 = [
            #"Summer19UL18_V5_MC_L1FastJet_AK4PFchs",
            #"Summer19UL18_V5_MC_L1RC_AK4PFchs",
	    "Summer19UL18_V5_MC_L2L3Residual_AK4PFchs",
	    "Summer19UL18_V5_MC_L2Residual_AK4PFchs",
            "Summer19UL18_V5_MC_L2Relative_AK4PFchs",
            "Summer19UL18_V5_MC_L3Absolute_AK4PFchs",
            "Summer19UL18_V5_MC_Uncertainty_AK4PFchs",
            #"Summer19UL18_JRV2_MC_PtResolution_AK4PFchs",
           #"Summer19UL18_JRV2_MC_SF_AK4PFchs",
        ]
        
        evaluator_ak4 = ext_ak4.make_evaluator()

        jec_inputs_ak4 = {name: evaluator_ak4[name] for name in jec_stack_names_ak4}
        jec_stack_ak4 = JECStack(jec_inputs_ak4)

        #ext_ak4res = extractor()
        #ext_ak4res.add_weight_sets([ #change to correct files
        #    #"* * jet_corrections/Summer19UL18_V5_MC_L1FastJet_AK4PFchs.txt", #looks to be 0,
        #    #"* * jet_corrections/Summer19UL18_V5_MC_L1RC_AK4PFchs.txt", #needs area
        #    #"* * jet_corrections/Summer19UL18_V5_MC_L2L3Residual_AK4PFchs.txt",
        #    "* * systematics/jetresolution_corrections/Summer19UL18_JRV2_MC_PtResolution_AK4PFchs.txt",
        #    "* * systematics/jetresolution_corrections/Summer19UL18_JRV2_MC_SF_AK4PFchs.txt",
        #])
        #ext_ak4res.finalize()
        #
        #jec_stack_names_ak4res = [
        #    "Summer19UL18_JRV2_MC_PtResolution_AK4PFchs",
        #    "Summer19UL18_JRV2_MC_SF_AK4PFchs",
        #]
        #
        #evaluator_ak4res = ext_ak4res.make_evaluator()
        #
        #jec_inputs_ak4res = {name: evaluator_ak4res[name] for name in jec_stack_names_ak4res}
        #jec_stack_ak4res = JECStack(jec_inputs_ak4res)

        ext_ak15 = extractor()
        ext_ak15.add_weight_sets([ #change to correct files
           # "* * jet_corrections/Summer19UL18_V5_MC_L1FastJet_AK4PFPuppi.txt" #looks to be 0,
            #"* * jet_corrections/Summer19UL18_V5_MC_L1RC_AK4PFchs.txt" #looks to be 0,
            "* * systematics/jetscale_corrections/Summer19UL18_V5_MC_L2Relative_AK8PFchs.txt",
            "* * systematics/jetscale_corrections/Summer19UL18_V5_MC_L3Absolute_AK8PFchs.txt", #looks to be 1, no change
            #"* * jet_corrections/Summer19UL18_V5_MC_Uncertainty_AK8PFchs.txt",
        ])
        ext_ak15.finalize()
        
        jec_stack_names_ak15 = [
            #"Fall17_17Nov2017_V32_MC_L2Relative_AK4PFPuppi",
            #"Fall17_17Nov2017_V32_MC_Uncertainty_AK4PFPuppi"
            #"Summer19UL18_V5_MC_L1FastJet_AK4PFPuppi",
            "Summer19UL18_V5_MC_L2Relative_AK8PFchs",
            "Summer19UL18_V5_MC_L3Absolute_AK8PFchs",
          #  "Summer19UL18_V5_MC_Uncertainty_AK8PFchs",
        ]
        
        evaluator_ak15 = ext_ak15.make_evaluator()
        
        jec_inputs_ak15 = {name: evaluator_ak15[name] for name in jec_stack_names_ak15}
        jec_stack_ak15 = JECStack(jec_inputs_ak15)
        #print(dir(evaluator))


        vals0 = ak.zip({
               'ht': arrays["ht"],
               'n_pfcand': arrays["n_pfcand"],
               'event_sphericity': arrays["event_sphericity"],
               'eventBoosted_sphericity': arrays["eventBoosted_sphericity"],
               'n_fatjet': arrays["n_fatjet"],
               'n_jetId': arrays["n_jetId"],
               'n_pfMu': arrays["n_pfMu"],
               'n_pfEl': arrays["n_pfEl"],
               'n_pvs': arrays["n_pvs"],
               'PU': arrays["PU_num"],
               'nPVs_good0': ak.count(arrays["Vertex_isValidVtx"],axis=-1),
               'nPVs_good1': ak.count(arrays["Vertex_isValidVtx"][(arrays["Vertex_isValidVtx"] == 1)],axis=-1),
               'nPVs_good2': ak.count(arrays["Vertex_isValidVtx"][(abs(arrays["Vertex_z"]) <24 ) & (arrays["Vertex_isValidVtx"] == 1)],axis=-1),
               'nPVs_good3': ak.count(arrays["Vertex_isValidVtx"][(abs(arrays["Vertex_z"]) < 24) & (arrays["Vertex_ndof"]> 4 ) & (arrays["Vertex_isValidVtx"] == 1)],axis=-1),
               'Vertex_tracksSize0': ak.max(arrays["Vertex_tracksSize"],axis=-1),
               'nPVs_good4': ak.count(arrays["Vertex_tracksSize"][arrays["Vertex_tracksSize"] >3],axis=-1),
               'nPVs_good5': ak.count(arrays["Vertex_tracksSize"][arrays["Vertex_tracksSize"] >5],axis=-1),
               'nPVs_good6': ak.count(arrays["Vertex_tracksSize"][arrays["Vertex_tracksSize"] >7],axis=-1),
               'nPVs_good7': ak.count(arrays["Vertex_tracksSize"][arrays["Vertex_tracksSize"] >10],axis=-1),
               'nPVs_good8': ak.count(arrays["Vertex_tracksSize"][arrays["Vertex_tracksSize"] >15],axis=-1),
               'nPVs_good9': ak.count(arrays["Vertex_tracksSize"][arrays["Vertex_tracksSize"] >25],axis=-1),
               'Vertex_minZ' : ak.min(abs(np.subtract(ak.firsts(arrays["Vertex_z"]),arrays["Vertex_z"][:,1:])),axis=-1,mask_identity=False),
               'triggerHt': tright,
               'triggerMu': trigmu,
               'PFcand_ncount0' :  ak.count(arrays["PFcand_pt"][(arrays["PFcand_q"] != 0) & (arrays["PFcand_vertex"] ==0) & (abs(arrays["PFcand_eta"]) < 2.4) & (arrays["PFcand_pt"]>0.0 )],axis=-1),
               'PFcand_ncount50' : ak.count(arrays["PFcand_pt"][(arrays["PFcand_q"] != 0) & (arrays["PFcand_vertex"] ==0) & (abs(arrays["PFcand_eta"]) < 2.4) & (arrays["PFcand_pt"]>0.50)],axis=-1),
               'PFcand_ncount60' : ak.count(arrays["PFcand_pt"][(arrays["PFcand_q"] != 0) & (arrays["PFcand_vertex"] ==0) & (abs(arrays["PFcand_eta"]) < 2.4) & (arrays["PFcand_pt"]>0.60)],axis=-1),
               'PFcand_ncount70' : ak.count(arrays["PFcand_pt"][(arrays["PFcand_q"] != 0) & (arrays["PFcand_vertex"] ==0) & (abs(arrays["PFcand_eta"]) < 2.4) & (arrays["PFcand_pt"]>0.70)],axis=-1),
               'PFcand_ncount75' : ak.count(arrays["PFcand_pt"][(arrays["PFcand_q"] != 0) & (arrays["PFcand_vertex"] ==0) & (abs(arrays["PFcand_eta"]) < 2.4) & (arrays["PFcand_pt"]>0.75)],axis=-1),
               'PFcand_ncount80' : ak.count(arrays["PFcand_pt"][(arrays["PFcand_q"] != 0) & (arrays["PFcand_vertex"] ==0) & (abs(arrays["PFcand_eta"]) < 2.4) & (arrays["PFcand_pt"]>0.80)],axis=-1),
               'PFcand_ncount90' : ak.count(arrays["PFcand_pt"][(arrays["PFcand_q"] != 0) & (arrays["PFcand_vertex"] ==0) & (abs(arrays["PFcand_eta"]) < 2.4) & (arrays["PFcand_pt"]>0.90)],axis=-1),
               'PFcand_ncount100': ak.count(arrays["PFcand_pt"][(arrays["PFcand_q"] != 0) & (arrays["PFcand_vertex"] ==0) & (abs(arrays["PFcand_eta"]) < 2.4) & (arrays["PFcand_pt"]>1.0 )],axis=-1),
               'PFcand_ncount150': ak.count(arrays["PFcand_pt"][(arrays["PFcand_q"] != 0) & (arrays["PFcand_vertex"] ==0) & (abs(arrays["PFcand_eta"]) < 2.4) & (arrays["PFcand_pt"]>1.5 )],axis=-1),
               'PFcand_ncount200': ak.count(arrays["PFcand_pt"][(arrays["PFcand_q"] != 0) & (arrays["PFcand_vertex"] ==0) & (abs(arrays["PFcand_eta"]) < 2.4) & (arrays["PFcand_pt"]>2   )],axis=-1),
               'PFcand_ncount300': ak.count(arrays["PFcand_pt"][(arrays["PFcand_q"] != 0) & (arrays["PFcand_vertex"] ==0) & (abs(arrays["PFcand_eta"]) < 2.4) & (arrays["PFcand_pt"]>3   )],axis=-1),
               #'FatJet_ncount30': ak.count(arrays["FatJet_pt"],axis=-1),
               #'FatJet_ncount50': ak.count(arrays["FatJet_pt"][arrays["FatJet_pt"]>50],axis=-1),
               #'FatJet_ncount100': ak.count(arrays["FatJet_pt"][arrays["FatJet_pt"]>100],axis=-1),
               #'FatJet_ncount150': ak.count(arrays["FatJet_pt"][arrays["FatJet_pt"]>150],axis=-1),
               #'FatJet_ncount200': ak.count(arrays["FatJet_pt"][arrays["FatJet_pt"]>200],axis=-1),
               #'FatJet_ncount250': ak.count(arrays["FatJet_pt"][arrays["FatJet_pt"]>250],axis=-1),
               #'FatJet_ncount300': ak.count(arrays["FatJet_pt"][arrays["FatJet_pt"]>300],axis=-1),
               'FatJet_nconst' : ak.max(arrays["FatJet_nconst"],axis=-1,mask_identity=False),
        })
        vals0["trigwgt"] = gettrigweights(vals0["ht"],trigSystematics)
        vals0["PUwgt"] = pileup_weight(2018,vals0["PU"],PUSystematics)
        vals0["wgt"] = vals0["trigwgt"]*vals0["PUwgt"]

        vals_vertex0 = ak.zip({
                      'Vertex_valid': arrays["Vertex_isValidVtx"],
                      'Vertex_tracksSize': arrays["Vertex_tracksSize"],
                      'Vertex_chi2': arrays["Vertex_chi2"],
                      'Vertex_ndof': arrays["Vertex_ndof"],
                      'Vertex_z': arrays["Vertex_z"],
        })
        vals_jet0 = ak.zip({
                       'pt' : arrays["Jet_pt"],
                       'eta': arrays["Jet_eta"],
                       'phi': arrays["Jet_phi"],
                       'mass': arrays["Jet_m"],
                       'area': arrays["Jet_area"],
                       'mass_raw': arrays["Jet_m"], # I think there should be another factor here?
                       'pt_raw': arrays["Jet_pt"],
                       'passId': arrays["Jet_passId"],
        },with_name="Momentum4D")
        print("loaded jet")
        name_map = jec_stack_ak4.blank_name_map
        name_map['JetPt'] = 'pt'
        name_map['JetMass'] = 'mass'
        name_map['JetEta'] = 'eta'
        name_map['JetA'] = 'area'
        name_map['massRaw'] = 'mass_raw'
        name_map['ptRaw'] = 'pt_raw'
        ##not sure these lines even do anything...
        #corrector = FactorizedJetCorrector(
        #Summer19UL18_V5_MC_L2Relative_AK4PFPuppi=evaluator['Summer19UL18_V5_MC_L2Relative_AK4PFPuppi'],
        #Summer19UL18_V5_MC_L3Absolute_AK4PFPuppi=evaluator['Summer19UL18_V5_MC_L3Absolute_AK4PFPuppi'],)
        #uncertainties = JetCorrectionUncertainty(
        # Summer19UL18_V5_MC_Uncertainty_AK4PFPuppi=evaluator['Summer19UL18_V5_MC_Uncertainty_AK4PFPuppi'])

        jet_factory = CorrectedJetsFactory(name_map, jec_stack_ak4)
        corrected_jets = jet_factory.build(vals_jet0, lazy_cache=arrays.caches[0])

        print("corrected jet")
        print('untransformed pt ratios', vals_jet0.pt/vals_jet0.pt_raw)
        print('untransformed mass ratios', vals_jet0.mass/vals_jet0.mass_raw)
        
        print('transformed pt ratios', corrected_jets.pt/corrected_jets.pt_raw)
        print('transformed mass ratios', corrected_jets.mass/corrected_jets.mass_raw)
        
        #print('JES pt ratio', corrected_jets.JES_jes.pt/corrected_jets.pt_raw)
        print('JES UP pt ratio', corrected_jets.JES_jes.up.pt/corrected_jets.pt_raw)
        print('JES DOWN pt ratio', corrected_jets.JES_jes.down.pt/corrected_jets.pt_raw)
        #vals_fatjet0 = ak.zip({
        #               'pt' : arrays["FatJet_pt"],
        #               'eta': arrays["FatJet_eta"],
        #               'phi': arrays["FatJet_phi"],
        #               'mass': arrays["FatJet_mass"],
        #               'FatJet_nconst': arrays["FatJet_nconst"],
        #}, with_name="Momentum4D")
        vals_nsub0 = ak.zip({
		"tau21": arrays["FatJet_tau21"],
		"tau32": arrays["FatJet_tau32"],
        })
        print("loaded fatjet")
        if(signal):
          alldRtracks = ak.zip({'PFcand_alldR': np.sqrt(arrays["PFcand_alldR"])})
          alldRtracks = ak.flatten(alldRtracks)
          vals_tracks0 = ak.zip({
                         'pt' : arrays["PFcand_pt"],
                         'eta': arrays["PFcand_eta"],
                         'phi': arrays["PFcand_phi"],
                         'mass': arrays["PFcand_m"],
                         'PFcand_dR':  np.sqrt(arrays["PFcand_dR"]),
                         'PFcand_fromsuep': arrays["PFcand_fromsuep"],
                         'PFcand_q': arrays["PFcand_q"],
                         'PFcand_vertex': arrays["PFcand_vertex"],
          },with_name="Momentum4D")
          vals_gen0 = ak.zip({
                         'pt' : arrays["gen_pt"],
                         'eta': arrays["gen_eta"],
                         'phi': arrays["gen_phi"],
                         'mass': arrays["gen_mass"],
                         'gen_dR':  np.sqrt(arrays["gen_dR"]),
                         'gen_fromSuep':  arrays["gen_fromSuep"],
                         'gen_PV':  arrays["gen_PV"],
                         'gen_PVdZ':  arrays["gen_PVdZ"],
          },with_name="Momentum4D")
          vals_gen0["wgt"] = vals0["wgt"]
          scalar0  = ak.zip({
                         'pt' : arrays["scalar_pt"],
                         'eta': arrays["scalar_eta"],
                         'phi': arrays["scalar_phi"],
                         'mass': arrays["scalar_m"],
                         'beta': arrays["scalar_m"]/arrays["scalar_pt"],
          },with_name="Momentum4D")
          scalar0["wgt"] = vals0["wgt"]
          #print(vals0['ht20'])
          
        else:
          vals_tracks0 = ak.zip({
                         'pt' : arrays["PFcand_pt"],
                         'eta': arrays["PFcand_eta"],
                         'phi': arrays["PFcand_phi"],
                         'mass': arrays["PFcand_m"],
                         'PFcand_q': arrays["PFcand_q"],
                         'PFcand_vertex': arrays["PFcand_vertex"],
          }, with_name="Momentum4D")
        print("loaded tracks")
        bCands = ak.zip({
            "pt":  [x for x in arrays["bPFcand_pt"]  if len(x) > 1],
            "eta": [x for x in arrays["bPFcand_eta"] if len(x) > 1],
            "phi": [x for x in arrays["bPFcand_phi"] if len(x) > 1],
            "mass":[x for x in arrays["bPFcand_m"]   if len(x) > 1] 
        }, with_name="Momentum4D") 
        if AK4sys ==1 :
        	vals0['ht20'] = ak.sum(corrected_jets.JES_jes.up["pt"][(corrected_jets["passId"] ==1) & (corrected_jets.JES_jes.up["pt"] > 20)],axis=-1)
        	vals0['ht30'] = ak.sum(corrected_jets.JES_jes.up["pt"][(corrected_jets["passId"] ==1) & (corrected_jets.JES_jes.up["pt"] > 30)],axis=-1)
        	vals0['ht40'] = ak.sum(corrected_jets.JES_jes.up["pt"][(corrected_jets["passId"] ==1) & (corrected_jets.JES_jes.up["pt"] > 40)],axis=-1)
        	vals0['ht50'] = ak.sum(corrected_jets.JES_jes.up["pt"][(corrected_jets["passId"] ==1) & (corrected_jets.JES_jes.up["pt"] > 50)],axis=-1)
        elif AK4sys ==2 :
        	vals0['ht20'] = ak.sum(corrected_jets.JES_jes.down["pt"][(corrected_jets["passId"] ==1) & (corrected_jets.JES_jes.down["pt"] > 20)],axis=-1)
        	vals0['ht30'] = ak.sum(corrected_jets.JES_jes.down["pt"][(corrected_jets["passId"] ==1) & (corrected_jets.JES_jes.down["pt"] > 30)],axis=-1)
        	vals0['ht40'] = ak.sum(corrected_jets.JES_jes.down["pt"][(corrected_jets["passId"] ==1) & (corrected_jets.JES_jes.down["pt"] > 40)],axis=-1)
        	vals0['ht50'] = ak.sum(corrected_jets.JES_jes.down["pt"][(corrected_jets["passId"] ==1) & (corrected_jets.JES_jes.down["pt"] > 50)],axis=-1)
        else:
        	vals0['ht20'] = ak.sum(corrected_jets["pt"][(corrected_jets["passId"] ==1) & (corrected_jets["pt"] > 20)],axis=-1)
        	vals0['ht30'] = ak.sum(corrected_jets["pt"][(corrected_jets["passId"] ==1) & (corrected_jets["pt"] > 30)],axis=-1)
        	vals0['ht40'] = ak.sum(corrected_jets["pt"][(corrected_jets["passId"] ==1) & (corrected_jets["pt"] > 40)],axis=-1)
        	vals0['ht50'] = ak.sum(corrected_jets["pt"][(corrected_jets["passId"] ==1) & (corrected_jets["pt"] > 50)],axis=-1)
        #vals0['ht20'] = ak.sum(arrays["Jet_pt"][(arrays["Jet_passId"] ==1) & (arrays["Jet_pt"] > 20)],axis=-1)
        #vals0['ht30'] = ak.sum(arrays["Jet_pt"][(arrays["Jet_passId"] ==1) & (arrays["Jet_pt"] > 30)],axis=-1)
        #vals0['ht40'] = ak.sum(arrays["Jet_pt"][(arrays["Jet_passId"] ==1) & (arrays["Jet_pt"] > 40)],axis=-1)
        #vals0['ht50'] = ak.sum(arrays["Jet_pt"][(arrays["Jet_passId"] ==1) & (arrays["Jet_pt"] > 50)],axis=-1)




        track_cuts = ((arrays["PFcand_q"] != 0) & (arrays["PFcand_vertex"] ==0) & (abs(arrays["PFcand_eta"]) < 2.4) & (arrays["PFcand_pt"]>=0.75))
        tracks_cut0 = vals_tracks0[track_cuts]
        if (killTrks):
          ntrk = ak.count(tracks_cut0,axis=None)#np.random.rand(3,2)
          np.random.seed(2022)
          rands = np.random.rand(ntrk) > 0.05
          trk_killer = ak.Array(ak.layout.ListOffsetArray64(tracks_cut0.layout.offsets, ak.layout.NumpyArray(rands)))# Array(rands).layout))
          tracks_cut0 = tracks_cut0[trk_killer]
        #print("ntrk: ",ntrk)
        #print("rands: ",rands)
        #print("trkkill: ",trk_killer)
	#did I need these lines? commenting out for now
        #tracks_cuts1 = ((tracks_cut0.x !=0)&(tracks_cut0.y !=0 )&(tracks_cut0.z !=0) &(tracks_cut0.p !=0))
        #tracks_cut0 = tracks_cut0[tracks_cuts1]

        minPt = 30
        jetdef = fastjet.JetDefinition(fastjet.antikt_algorithm,1.5)
        cluster = fastjet.ClusterSequence(tracks_cut0,jetdef)
        ak_inclusive_jets0 = ak.with_name(cluster.inclusive_jets(),"Momentum4D")
        ak_inclusive_cluster = ak.with_name(cluster.constituents(),"Momentum4D")
        ak_inclusive_jets0["pt"] = ak_inclusive_jets0.pt
        ak_inclusive_jets0["eta"] = ak_inclusive_jets0.eta
        ak_inclusive_jets0["phi"] = ak_inclusive_jets0.phi
        ak_inclusive_jets0["mass"] = ak_inclusive_jets0.m
        ak_inclusive_jets0["pt_raw"] = ak_inclusive_jets0.pt
        ak_inclusive_jets0["mass_raw"] = ak_inclusive_jets0.m


        jet_factory_ak15 = CorrectedJetsFactory(name_map, jec_stack_ak15)
        ak_inclusive_jets = jet_factory_ak15.build(ak_inclusive_jets0, lazy_cache=arrays.caches[0])
        #ak_inclusive_jets = ak_inclusive_jets.JES_jes.up

        minPtCut = ak_inclusive_jets.pt > minPt
        ak_inclusive_jets = ak_inclusive_jets[minPtCut]
        ak_inclusive_cluster = ak_inclusive_cluster[minPtCut]
        highpt_jet = ak.argsort(ak_inclusive_jets.pt, axis=1, ascending=False, stable=True)
        jets_sorted = ak_inclusive_jets[highpt_jet]
        cluster_sorted = ak_inclusive_cluster[highpt_jet]
        
        vals_fatjet0 =ak.zip({
            "pt": jets_sorted.pt,
            "eta": jets_sorted.eta,
            "phi": jets_sorted.phi,
            "mass": jets_sorted.m,
            "FatJet_nconst": ak.num(cluster_sorted,axis=-1),
        }, with_name="Momentum4D")
        vals0["FatJet_ncount30"] = ak.count(vals_fatjet0["pt"][vals_fatjet0["pt"]>30],axis=-1)
        vals0["FatJet_ncount50"] = ak.count(vals_fatjet0["pt"][vals_fatjet0["pt"]>50],axis=-1)
        vals0["FatJet_ncount100"] = ak.count(vals_fatjet0["pt"][vals_fatjet0["pt"]>100],axis=-1)
        vals0["FatJet_ncount150"] = ak.count(vals_fatjet0["pt"][vals_fatjet0["pt"]>150],axis=-1)
        vals0["FatJet_ncount200"] = ak.count(vals_fatjet0["pt"][vals_fatjet0["pt"]>200],axis=-1)
        vals0["FatJet_ncount250"] = ak.count(vals_fatjet0["pt"][vals_fatjet0["pt"]>250],axis=-1)
        vals0["FatJet_ncount300"] = ak.count(vals_fatjet0["pt"][vals_fatjet0["pt"]>300],axis=-1)


        jets_pTsorted  = vals_fatjet0[ vals0["FatJet_ncount30"] >=2]
        clusters_pTsorted  = cluster_sorted[ vals0["FatJet_ncount30"] >= 2] 
        #vals_nsub  = vals_nsub0[ ak.count(vals_nsub0["tau21"],axis=-1) >=2]
        #vals_nsub  = vals_nsub0[ vals0["FatJet_ncount30"] >=2]
        reSUEP_cand = ak.where(jets_pTsorted.FatJet_nconst[:,1] <=jets_pTsorted.FatJet_nconst[:,0],clusters_pTsorted[:,0],clusters_pTsorted[:,1])
        reISR_cand  = ak.where(jets_pTsorted.FatJet_nconst[:,1] > jets_pTsorted.FatJet_nconst[:,0],clusters_pTsorted[:,0],clusters_pTsorted[:,1])
        SUEP_cand   = ak.where(jets_pTsorted.FatJet_nconst[:,1] <=jets_pTsorted.FatJet_nconst[:,0],jets_pTsorted[:,0],jets_pTsorted[:,1])
        ISR_cand    = ak.where(jets_pTsorted.FatJet_nconst[:,1] > jets_pTsorted.FatJet_nconst[:,0],jets_pTsorted[:,0],jets_pTsorted[:,1])
        #print(vals_nsub)
        #print(vals_nsub[:,0])
        #SUEP_nsub = ak.where(jets_pTsorted.FatJet_nconst[:,1] <=jets_pTsorted.FatJet_nconst[:,0],vals_nsub[:,0],vals_nsub[:,1])
        #SUEP_nsub = vals_nsub[:,0] #just take leading for now

        if (redoISRRM):
          print("calc sphericity")
          boost_IRM = ak.zip({
              "px": SUEP_cand.px*-1,
              "py": SUEP_cand.py*-1,
              "pz": SUEP_cand.pz*-1,
              "mass": SUEP_cand.mass
          }, with_name="Momentum4D")
          ISR_cand_b = ISR_cand.boost_p4(boost_IRM) # boosted ISR jet

          recotracks_IRM = tracks_cut0[vals0["FatJet_ncount30"] >= 2] # tracks
          tracks_IRM = recotracks_IRM.boost_p4(boost_IRM) # boosted tracks
          tracks_cuts1x = (tracks_IRM.p !=0)
          tracks_IRM = tracks_IRM[tracks_cuts1x]

          spherex0 = vals0[vals0["FatJet_ncount30"] >= 2]
          spherex0["FatJet_nconst"] = SUEP_cand["FatJet_nconst"]
          spherex0["SUEP_pt"] = SUEP_cand["pt"]
          spherex0["SUEP_eta"] = SUEP_cand["eta"]
          spherex0["SUEP_phi"] = SUEP_cand["phi"]
          spherex0["SUEP_mass"] = SUEP_cand["mass"]
          spherex0["SUEP_beta"] = SUEP_cand["mass"]/SUEP_cand["pt"]
          spherex0["ISR_pt"]   = ISR_cand["pt"]
          spherex0["ISR_eta"]  = ISR_cand["eta"]
          spherex0["ISR_phi"]  = ISR_cand["phi"]
          spherex0["ISR_mass"] = ISR_cand["mass"]
          spherex0["ISR_beta"] = ISR_cand["mass"]/ISR_cand["pt"]

          #print(reSUEP_cand)
          #print(tracks_cut0)
          #spherex0["SUEP_tau21"] = SUEP_nsub["tau21"] 
          #spherex0["SUEP_tau32"] = SUEP_nsub["tau32"] 

          #spherex0["SUEP_tau1"] = nSubjettiness(1,SUEP_cand,reSUEP_cand) 
          #spherex0["SUEP_tau1"] = nSubjettiness(2,SUEP_cand,tracks_cut0) 
          #print(spherex0["SUEP_tau21"])
          #spherex0["SUEP_tau2"] = nSubjettiness(2,SUEP_cand,reSUEP_cand)
          #spherex0["SUEP_tau3"] = nSubjettiness(3,SUEP_cand,reSUEP_cand)
          #spherex0["SUEP_tau12"] = spherex0["SUEP_tau1"]/spherex0["SUEP_tau2"]
          #spherex0["SUEP_tau23"] = spherex0["SUEP_tau2"]/spherex0["SUEP_tau3"]
          spherex0["SUEP_girth"],spherex0["SUEP_ptDispersion"],spherex0["SUEP_lesHouches"],spherex0["SUEP_thrust"] = jetAngularities(SUEP_cand,reSUEP_cand)
          #print("girth: ",spherex0["SUEP_girth"])
          #print("ptDispersion: ",spherex0["SUEP_ptDispersion"])
          #print("lesHouches: ",spherex0["SUEP_lesHouches"])
          #print("thrust: ",spherex0["SUEP_thrust"])
        
          reSUEP_cand = reSUEP_cand.boost_p4(boost_IRM)
          tracks_cuts2x = (reSUEP_cand.p !=0)
          reSUEP_cand = reSUEP_cand[tracks_cuts2x]
          reonetrackcut = (ak.num(reSUEP_cand) >=2) 
          reSUEP_cand = reSUEP_cand[reonetrackcut]
          spherey0 = spherex0[reonetrackcut]
          if(len(reSUEP_cand)!=0):
            reeigs2 = sphericity(self,reSUEP_cand,2.0) # normal sphericity
            reeigs1 = sphericity(self,reSUEP_cand,1.0) # sphere 1
            spherey0["sphere1_suep"] = 1.5 * (reeigs1[:,1]+reeigs1[:,0])
            spherey0["sphere_suep"] = 1.5 * (reeigs2[:,1]+reeigs2[:,0])

            spherey0["cparam1_suep"] = 3 * (reeigs1[:,0]*reeigs1[:,1]+reeigs1[:,0]*reeigs1[:,2]+reeigs1[:,1]*reeigs1[:,2])
            spherey0["cparam_suep"] = 3 * (reeigs2[:,0]*reeigs2[:,1]+reeigs2[:,0]*reeigs2[:,2]+reeigs2[:,1]*reeigs2[:,2])
            spherey0["dparam1_suep"] = 27 * (reeigs1[:,2]*reeigs1[:,1]*reeigs1[:,0])
            spherey0["dparam_suep"] = 27 * (reeigs2[:,2]*reeigs2[:,1]*reeigs2[:,0])
            spherey0["aplanarity1_suep"] = 1.5 * (reeigs1[:,0])
            spherey0["aplanarity_suep"] = 1.5 * (reeigs2[:,0])
          else:
            spherey0["sphere1_suep"] = -1 
            spherey0["sphere_suep"] = -1
            spherey0["cparam1_suep"] = -1 
            spherey0["cparam_suep"] = -1
            spherey0["dparam1_suep"] = -1 
            spherey0["dparam_suep"] = -1
            spherey0["aplanarity1_suep"] = -1 
            spherey0["aplanarity_suep"] = -1
          
          spherey1 = spherey0[spherey0.triggerHt >= 1]
          spherey2 = spherey1[spherey1.ht >= 600]
          spherey3 = spherey2[spherey2.FatJet_ncount50 >= 2]
          spherey4 = spherey3[spherey3.FatJet_nconst >= 70]
          sphere1y = [spherey0,spherey1,spherey2,spherey3,spherey4]#,spherey5,spherey6]

          #wgts = trigwgts
          output = packdist(output,sphere1y,"cparam1_suep")
          output = packdist(output,sphere1y,"cparam_suep")
          output = packdist(output,sphere1y,"dparam1_suep")
          output = packdist(output,sphere1y,"dparam_suep")
          output = packdist(output,sphere1y,"aplanarity1_suep")
          output = packdist(output,sphere1y,"aplanarity_suep")

          output = packdist(output,sphere1y,"sphere1_suep")
          output = packdist(output,sphere1y,"sphere_suep")
          output = packSR(output,sphere1y,"suep")
          output = packdist(output,sphere1y,"SUEP_beta")
          output = packdist(output,sphere1y,"SUEP_pt")
          output = packdist(output,sphere1y,"SUEP_eta")
          output = packdist(output,sphere1y,"SUEP_phi")
          output = packdist(output,sphere1y,"SUEP_mass")
          output = packdist(output,sphere1y,"ISR_beta")
          output = packdist(output,sphere1y,"ISR_pt")
          output = packdist(output,sphere1y,"ISR_eta")
          output = packdist(output,sphere1y,"ISR_phi")
          output = packdist(output,sphere1y,"ISR_mass")
          output = packdist(output,sphere1y,"SUEP_girth")
          output = packdist(output,sphere1y,"SUEP_ptDispersion")
          output = packdist(output,sphere1y,"SUEP_lesHouches")
          output = packdist(output,sphere1y,"SUEP_thrust")
#          output = packdist(output,sphere1y,"SUEP_tau12")
#          output = packdist(output,sphere1y,"SUEP_tau32")
          #################################ISR################################
          boost_IRMxx = ak.zip({
              "px": ISR_cand.px*-1,
              "py": ISR_cand.py*-1,
              "pz": ISR_cand.pz*-1,
              "mass": ISR_cand.mass
          }, with_name="Momentum4D")
          #ISR_cand_bxx = ISR_cand.boost_p4(boost_IRMxx) # boosted ISR jet

          recotracks_IRMxx = tracks_cut0[vals0["FatJet_ncount30"] >= 2] # tracks
          tracks_IRMxx = recotracks_IRMxx.boost_p4(boost_IRMxx) # boosted tracks
          tracks_cuts1xxx = (tracks_IRMxx.p !=0)
          tracks_IRMxx = tracks_IRMxx[tracks_cuts1xxx]

          reISR_cand = reISR_cand.boost_p4(boost_IRMxx)
          tracks_cuts2xxx = (reISR_cand.p !=0)
          reISR_cand = reISR_cand[tracks_cuts2xxx]
          reonetrackcutxx = (ak.num(reISR_cand) >=2) 
          reISR_cand = reISR_cand[reonetrackcutxx]
          spherey0xx = spherex0[reonetrackcutxx]
          if(len(reSUEP_cand)!=0):
            reeigs2xx = sphericity(self,reISR_cand,2.0) # normal sphericity
            reeigs1xx = sphericity(self,reISR_cand,1.0) # sphere 1
            spherey0xx["sphere1_isrsuep"] = 1.5 * (reeigs1xx[:,1]+reeigs1xx[:,0])
            spherey0xx["sphere_isrsuep"] = 1.5 * (reeigs2xx[:,1]+reeigs2xx[:,0])
          else:
            spherey0xx["sphere1_isrsuep"] = -1 
            spherey0xx["sphere_isrsuep"] = -1
          
          spherey1xx = spherey0xx[spherey0xx.triggerHt >= 1]
          spherey2xx = spherey1xx[spherey1xx.ht >= 600]
          spherey3xx = spherey2xx[spherey2xx.FatJet_ncount50 >= 2]
          spherey4xx = spherey3xx[spherey3xx.FatJet_nconst >= 70]
          sphere1yxx = [spherey0xx,spherey1xx,spherey2xx,spherey3xx,spherey4xx]#,spherey5,spherey6]
          output = packdist(output,sphere1yxx,"sphere1_isrsuep")
          output = packdist(output,sphere1yxx,"sphere_isrsuep")
          output = packSR(output,sphere1yxx,"isrsuep")
          #################################ISR################################
          if(eventDisplay_knob):
            for evt in range(20):
              print(evt)
              plot_display(evt,spherey0["ht"][evt],recotracks_IRM[evt],tracks_IRM[evt],SUEP_cand[evt],ISR_cand[evt],ISR_cand_b[evt],spherey0["sphere1_suep"][evt],reSUEP_cand[evt],reISR_cand[evt])
          IRM_candsvx2 = tracks_IRM[abs(recotracks_IRM[tracks_cuts1x].deltaR(ISR_cand)) >= 1.5] # remove all tracks that would be in the ISR jet unboosted
          reonetrackcutx = (ak.num(IRM_candsvx2) >=2)
          IRM_candsvx2 = IRM_candsvx2[reonetrackcutx]
          spherez0 = spherex0[reonetrackcutx]
          if(len(IRM_candsvx2)!=0):
            rexeigs2 = sphericity(self,IRM_candsvx2,2.0) # normal sphericity
            rexeigs1 = sphericity(self,IRM_candsvx2,1.0) # sphere 1
            spherez0["sphere1_isr"] = 1.5 * (rexeigs1[:,1]+rexeigs1[:,0])
            spherez0["sphere_isr"] = 1.5 * (rexeigs2[:,1]+rexeigs2[:,0])
          else:
            spherez0["sphere1_isr"] = -1 
            spherez0["sphere_isr"] = -1
          spherez1 = spherez0[spherez0.triggerHt >= 1]
          spherez2 = spherez1[spherez1.ht >= 600]
          spherez3 = spherez2[spherez2.FatJet_ncount50 >= 2]
          spherez4 = spherez3[spherez3.FatJet_nconst >= 70]
          sphere1z = [spherez0,spherez1,spherez2,spherez3,spherez4]#,spherez5,spherez6]
          output = packdist(output,sphere1z,"sphere1_isr")
          output = packdist(output,sphere1z,"sphere_isr")
          output = packSR(output,sphere1z,"isr")

          def sphericityCalc(output,cut):
            IRM_cands = tracks_IRM[abs(tracks_IRM.deltaphi(ISR_cand_b)) >= cut/10.]
            onetrackcut = (ak.num(IRM_cands) >=2) # cut to pick out events that survive the isr removal
            IRM_cands = IRM_cands[onetrackcut]
            spherexx = spherex0[onetrackcut]
            #IRM_cands = ak.mask(IRM_cands,onetrackcut)
  

            print(len(IRM_cands),len(spherex0))
            if(len(IRM_cands)!=0):
              eigs2 = sphericity(self,IRM_cands,2.0) # normal sphericity
              eigs1 = sphericity(self,IRM_cands,1.0) # sphere 1
              spherexx["sphere1_%s"%cut] = 1.5 * (eigs1[:,1]+eigs1[:,0])
              spherexx["sphere_%s"%cut] = 1.5 * (eigs2[:,1]+eigs2[:,0])
            else:
              spherexx["sphere1_%s"%cut] = -1 
              spherexx["sphere_%s"%cut] = -1
            spherex1 = spherexx[spherexx.triggerHt >= 1]
            spherex2 = spherex1[spherex1.ht >= 600]
            spherex3 = spherex2[spherex2.FatJet_ncount50 >= 2]
            spherex4 = spherex3[spherex3.FatJet_nconst >= 70]
            #spherex4 = spherex3[spherex3.PFcand_ncount75 >= 140]
            #spherex5 = spherex2[spherex2.n_pvs < 30]
            #spherex6 = spherex2[spherex2.n_pvs <= 30]
            sphere1 = [spherexx,spherex1,spherex2,spherex3,spherex4]#,spherex5,spherex6]
            output = packdist(output,sphere1,"sphere1_%s"%cut)
            output = packdist(output,sphere1,"sphere_%s"%cut)
            output = packSR(output,sphere1,cut)
            del sphere1
            del spherexx
            del spherex1
            del spherex2
            del spherex3
            del spherex4
            #del spherex5
            #del spherex6
            return output
          output = sphericityCalc(output,16)
          output = sphericityCalc(output,10)
          output = sphericityCalc(output,8)
          output = sphericityCalc(output,4)

          print("filling cutflows") 
        
       ## resolution studies
        if(signal):
          print("calc res")
          scalar1  = scalar0[ vals0["FatJet_ncount30"] >= 2] 
          suepvals = vals0[vals0.FatJet_ncount30 >=2]
          suepvalsx = suepvals[suepvals.triggerHt >=1]
          #suepvalsxx = suepvalsx[suepvals.triggerHt >=1]
          #SUEP_candq = SUEP_cand[(suepvals.triggerHt >=1) & (suepvals.ht>=600)] # FJ > 2 cut is already applied from the suep array
          #SUEP_candqqq = SUEP_cand # FJ > 2 cut is already applied from the suep array
          #SUEP_candqq = SUEP_candqqq[suepvals.triggerHt >=1] # FJ > 2 cut is already applied from the suep array
          #SUEP_candq = SUEP_candqq[suepvalsx.ht>=600] # FJ > 2 cut is already applied from the suep array
          scalar2 = scalar1[suepvals.triggerHt >=1] # FJ > 2 cut is already applied from the suep array
          scalar = scalar2[suepvalsx.ht>=600] # FJ > 2 cut is already applied from the suep array
          #scalar = scalar1[(suepvals.triggerHt >=1) & (suepvals.ht>=600)] # FJ > 2 cut is already applied from the suep array
          #print(len(scalar), len(SUEP_candq),len(SUEP_candqq),len(SUEP_candqqq))
          #res_pt = SUEP_candq.pt.to_numpy()#-scalar["pt"].to_numpy()#/scalar["pt"].to_numpy()
          #res_pt = SUEP_candqq.mass.to_numpy()#-scalar["mass"].to_numpy()#/scalar["mass"].to_numpy()
          #res_dR = SUEP_candqqq.mass.to_numpy()#-scalar["mass"].to_numpy()#/scalar["mass"].to_numpy()
          #res_mass = SUEP_candq.mass.to_numpy()#-scalar["mass"].to_numpy()#/scalar["mass"].to_numpy()
          res_beta = spherey2["SUEP_beta"]-scalar["beta"].to_numpy()
          res_pt = spherey2["SUEP_pt"]-scalar["pt"].to_numpy()
          res_mass = spherey2["SUEP_mass"]-scalar["mass"].to_numpy()
          print("res mass: ",len(res_mass))
          phi1 = spherey2["SUEP_phi"].to_numpy()
          phi2 = scalar["phi"].to_numpy()
          res_dPhi0 = phi1-phi2 #SUEP_cand.phi.to_numpy()-scalar["phi"].to_numpy()
          #res_dPhi = phi1-phi2 #SUEP_cand.phi.to_numpy()-scalar["phi"].to_numpy()
          res_dPhi00 = np.array([2*np.pi-x if x > np.pi else x for x in res_dPhi0])
          res_dPhi = np.array([2*np.pi+x if x < -np.pi else x for x in res_dPhi00])
          #res_dPhi = SUEP_cand.phi.to_numpy()-scalar["phi"].to_numpy()
          res_dEta = spherey2["SUEP_eta"].to_numpy()-scalar["eta"].to_numpy()
          res_dR = np.sqrt(np.square(res_dPhi) + np.square(res_dEta))
          resolutions = ak.zip({
            "res_pt" : res_pt,
            "res_mass" : res_mass,
            "res_dEta" : res_dEta,
            "res_dPhi" : res_dPhi,
            "res_dR" : res_dR,
            "res_beta" : res_beta
        
          })
          resolutions["wgt"] = spherey2["wgt"]
       ############################################################################## 
        #cutflow Ht
        vals1 = vals0[vals0.triggerHt >= 1]
        vals2 = vals1[vals1.ht >= 600]
        vals3 = spherey3 #vals2[vals2.FatJet_ncount50 >= 2]
        vals4 = vals3[vals3.FatJet_nconst >= 70]
        vals5 = vals4[vals4.sphere1_suep >= 0.7]
        vals4x = vals3[vals3.sphere1_suep >= 0.7]


        vals_jet1 = corrected_jets[vals0.triggerHt >= 1]
        vals_jet2 = vals_jet1[vals1.ht >= 600]
        vals_jet3 = vals_jet2[vals2.FatJet_ncount50 >= 2]
        vals_jet4 = vals_jet3[vals3.FatJet_nconst >= 70]
        
        print("filling cutflows fj") 
        vals_fatjet1 = vals_fatjet0[vals0.triggerHt >= 1]
        vals_fatjet2 = vals_fatjet1[vals1.ht >= 600]
        vals_fatjet3 = vals_fatjet2[vals2.FatJet_ncount50 >= 2]
        vals_fatjet4 = vals_fatjet3[vals3.FatJet_nconst >= 70]

        vals_nsub1 = vals_nsub0[vals0.triggerHt >= 1]
        vals_nsub2 = vals_nsub1[vals1.ht >= 600]
        vals_nsub3 = vals_nsub2[vals2.FatJet_ncount50 >= 2]
        vals_nsub4 = vals_nsub3[vals3.FatJet_nconst >= 70]
        #vals_fatjet4 = vals_fatjet3[vals3.PFcand_ncount75 >= 140]
        #print("filling ") 
        #vals_ = vals_fatjet0[vals0.triggerHt >= 1]
        #vals_ = vals_fatjet1[vals1.ht >= 600]
        #vals_ = vals_fatjet2[vals2.FatJet_ncount50 >= 2]
        #vals_ = vals_fatjet3[vals3.FatJet_nconst >= 70]
        
        #vals_refatjet1 = vals_refatjet0[vals0.triggerHt >=1]
        #vals_refatjet2 = vals_refatjet1[vals1.ht >= 600]
        #vals_refatjet3 = vals_refatjet2[vals2.FatJet_ncount50 >= 2]
        #vals_refatjet4 = vals_refatjet3[vals3.FatJet_nconst >= 70]
        ##vals_refatjet4 = vals_refatjet3[vals3.PFcand_ncount75 >= 140]
        
     
        print("filling cutflows trk") 
        vals_tracks1 = tracks_cut0[vals0.triggerHt >= 1]
        vals_tracks2 = vals_tracks1[vals1.ht >= 600]
        vals_tracks3 = vals_tracks2[vals2.FatJet_ncount50 >= 2]
        vals_tracks4 = vals_tracks3[vals3.FatJet_nconst >= 70]
        #vals_tracks4 = vals_tracks3[vals3.PFcand_ncount75 >= 140]
        print("filling cutflows vertex") 
        vals_vertex1 = vals_vertex0[vals0.triggerHt >= 1]
        vals_vertex2 = vals_vertex1[vals1.ht >= 600]
        vals_vertex3 = vals_vertex2[vals2.FatJet_ncount50 >= 2]
        vals_vertex4 = vals_vertex3[vals3.FatJet_nconst >=70]
        #vals_vertex4 = vals_vertex3[vals3.PFcand_ncount75 >=140]

        vals = [vals0,vals1,vals2,vals3,vals4,vals5]
        valsx = [vals0,vals1,vals2,vals3,vals4x]
        vals_jet = [corrected_jets,vals_jet1,vals_jet2,vals_jet3,vals_jet4]
        vals_fatjet = [vals_fatjet0,vals_fatjet1,vals_fatjet2,vals_fatjet3,vals_fatjet4]
        vals_nsub = [vals_nsub0,vals_nsub1,vals_nsub2,vals_nsub3,vals_nsub4]
        #vals_refatjet = [vals_refatjet0,vals_refatjet1,vals_refatjet2,vals_refatjet3,vals_refatjet4]
        vals_tracks = [vals_tracks0,vals_tracks1,vals_tracks2,vals_tracks3,vals_tracks4]
        vals_vertex = [vals_vertex0,vals_vertex1,vals_vertex2,vals_vertex3,vals_vertex4]

        #fatjet n-1 cutflow
        #fj3 = vals2[vals2.PFcand_ncount75 >=140]
        #fj4 = fj3[fj3.eventBoosted_sphericity >= 0.6]
        fj3 = spherey2[spherey2.FatJet_nconst >=70]
        fj4 = fj3[fj3.sphere1_suep >= 0.7]
        vals_fj = [vals0,vals1,vals2,fj3,fj4]


        #trig cutflow
        trig1 = vals0[vals0.triggerMu >=1]
        trig2 = vals0[vals0.triggerHt >=1]
        trig3 = trig1[trig1.triggerHt >=1]
        trigs = [vals0,trig1,trig2,trig3]

        if(signal):
          print("filling cutflows trkID") 
          trkID1 = vals_tracks0[(vals0.triggerHt >= 1) & (vals0.ht >=600) ]
          #trkID1 = vals_tracks0[(vals0.triggerHt >= 1) & (vals0.ht >=600) &(vals0.FatJet_ncount50 >= 2)]

          trkID2 = trkID1[abs(trkID1.eta) < 2.4]
          trkID3 = trkID2[trkID2.PFcand_q != 0]
          trkID4 = trkID3[trkID3.PFcand_vertex == 0]
          trkID5 = trkID4[trkID4.pt > 0.5]
          trkID6 = trkID5[trkID5.pt > 0.6]
          trkID7 = trkID6[trkID6.pt > 0.7]
          trkID8 = trkID7[trkID7.pt > 0.75]
          trkID9 = trkID8[trkID8.pt > 0.8]
          trkID10 = trkID9[trkID9.pt > 0.9]
          trkID11 = trkID10[trkID10.pt > 1.0]
          trkID = [trkID1,trkID2,trkID3,trkID4,trkID5,trkID6,trkID7,trkID8,trkID9,trkID10,trkID11]
          output = packtrkFKID(output,trkID,"pt" ,"PFcand_dR","PFcand_")
          output = packtrkFKID(output,trkID,"eta","PFcand_dR","PFcand_")
          output = packtrkFKID(output,trkID,"phi","PFcand_dR","PFcand_")
          #print("tracks pf: ",len(ak.flatten(trkID1)),len(ak.flatten(trkID2)),len(ak.flatten(trkID3)),len(ak.flatten(trkID4)),len(ak.flatten(trkID5)),len(ak.flatten(trkID6)),len(ak.flatten(trkID7)),len(ak.flatten(trkID8)),len(ak.flatten(trkID9)),len(ak.flatten(trkID10)),len(ak.flatten(trkID11)))

          vals_gen1 = vals_gen0[vals0.triggerHt >= 1]
          vals_gen2 = vals_gen1[vals1.ht >= 600]
          vals_gen3 = vals_gen2[vals2.FatJet_ncount50 >= 2]
          vals_gen4 = vals_gen3[vals3.FatJet_nconst >= 70]
          #vals_gen4 = vals_gen3[vals3.n_pfcand >= 140]
          vals_gen = [vals_gen0,vals_gen1,vals_gen2,vals_gen3,vals_gen4]
          vals_scalar1 = scalar0[vals0.triggerHt >= 1]
          vals_scalar2 = vals_scalar1[vals1.ht >= 600]
          vals_scalar3 = vals_scalar2[vals2.FatJet_ncount50 >= 2]
          vals_scalar4 = vals_scalar3[vals3.FatJet_nconst >= 70]
          #valsscalarn4 = valsscalarn3[vals3.n_pfcand >= 140]
          vals_scalar = [scalar0,vals_scalar1,vals_scalar2,vals_scalar3,vals_scalar4]

          trkID5x = vals_gen2[vals_gen2.pt > 0.5]
          #trkID5x = vals_gen3[vals_gen3.pt > 0.5]
          trkID6x = trkID5x[trkID5x.pt > 0.6]
          trkID7x = trkID6x[trkID6x.pt > 0.7]
          trkID8x = trkID7x[trkID7x.pt > 0.75]
          trkID9x = trkID8x[trkID8x.pt > 0.8]
          trkID10x = trkID9x[trkID9x.pt > 0.9]
          trkID11x = trkID10x[trkID10x.pt > 1.0]
          trkIDx = [vals_gen3,trkID5x,trkID6x,trkID7x,trkID8x,trkID9x,trkID10x,trkID11x]

          #vals_genpv = vals_gen3[vals_gen3.gen_PV == 0]
          #trkID5xx = vals_genpv[vals_genpv.pt > 0.5]
          #trkID6xx = trkID5xx[trkID5xx.pt > 0.6]
          #trkID7xx = trkID6xx[trkID6xx.pt > 0.7]
          #trkID8xx = trkID7xx[trkID7xx.pt > 0.75]
          #trkID9xx = trkID8xx[trkID8xx.pt > 0.8]
          #trkID10xx = trkID9xx[trkID9xx.pt > 0.9]
          #trkID11xx = trkID10xx[trkID10xx.pt > 1.0]
          #trkIDxPV = [vals_genPV,trkID5xx,trkID6xx,trkID7xx,trkID8xx,trkID9xx,trkID10xx,trkID11xx]

          #output = packtrkID(output,trkIDxPV,"pt" ,"gen_dR","genPV_")
          #output = packtrkID(output,trkIDxPV,"eta","gen_dR","genPV_")
          #output = packtrkID(output,trkIDxPV,"phi","gen_dR","genPV_")
          output = packtrkID(output,trkIDx,"pt" ,"gen_dR","gen_PV","gen_")
          output = packtrkID(output,trkIDx,"eta","gen_dR","gen_PV","gen_")
          output = packtrkID(output,trkIDx,"phi","gen_dR","gen_PV","gen_")
          output = packdist(output,vals_scalar,"pt","scalar_")
          output = packdist(output,vals_scalar,"eta","scalar_")
          output = packdist(output,vals_scalar,"phi","scalar_")
          output = packdist(output,vals_scalar,"mass","scalar_")
          output = packdist(output,vals_scalar,"beta","scalar_")
          output = packdistflat(output,vals_tracks,"PFcand_dR")
          output = packdistflat(output,vals_gen,"pt","gen_")
          output = packdistflat(output,vals_gen,"gen_dR")
          output = packdistflat(output,vals_gen,"eta","gen_")
          output = packdistflat(output,vals_gen,"phi","gen_")
          output = packdistflat(output,vals_gen,"gen_PV")
          output = packdistflat(output,vals_gen,"gen_PVdZ")
          output = packsingledist(output,alldRtracks,"PFcand_alldR",wgt=False)
          output = packsingledist(output,resolutions,"res_beta")
          output = packsingledist(output,resolutions,"res_pt")
          output = packsingledist(output,resolutions,"res_mass")
          output = packsingledist(output,resolutions,"res_dR")
          output = packsingledist(output,resolutions,"res_dPhi")
          output = packsingledist(output,resolutions,"res_dEta")
          output = packtrig(output,trigs,"ht20")
          output = packtrig(output,trigs,"ht30")
          output = packtrig(output,trigs,"ht40")
          output = packtrig(output,trigs,"ht50")

        output = packtrig(output,trigs,"ht")
     
        output = packtrig(output,trigs,"n_pfMu")
        output = packtrig(output,trigs,"event_sphericity")
        output = packtrig(output,trigs,"FatJet_nconst")
        output = packtrig2D(output,trigs,"ht","event_sphericity")
        output = packtrig2D(output,trigs,"ht","FatJet_nconst")
        #fill hists
        print("filling hists") 
        output = packdist(output,vals,"ht")
        output = packdist(output,vals,"n_pfcand")
        output = packdist(output,vals,"event_sphericity")
        output = packdist(output,vals,"eventBoosted_sphericity")
        output = packdist(output,vals,"n_fatjet")
        output = packdist(output,vals,"n_jetId")
        output = packdist(output,vals,"n_pfMu")
        output = packdist(output,vals,"n_pfEl")
        output = packdist(output,vals,"n_pvs")
        output = packdist(output,vals,"nPVs_good0")
        output = packdist(output,vals,"nPVs_good1")
        output = packdist(output,vals,"nPVs_good2")
        output = packdist(output,vals,"nPVs_good3")
        output = packdist(output,vals,"nPVs_good4")
        output = packdist(output,vals,"nPVs_good5")
        output = packdist(output,vals,"nPVs_good6")
        output = packdist(output,vals,"nPVs_good7")
        output = packdist(output,vals,"nPVs_good8")
        output = packdist(output,vals,"nPVs_good9")
        output = packdist(output,vals,"Vertex_minZ")
        output = packdist(output,vals,"Vertex_tracksSize0")
        output = packdistflat(output,vals_vertex,"Vertex_valid","")
        output = packdistflat(output,vals_vertex,"Vertex_tracksSize","")
        output = packdistflat(output,vals_vertex,"Vertex_chi2","")
        output = packdistflat(output,vals_vertex,"Vertex_ndof","")
        output = packdistflat(output,vals_vertex,"Vertex_z","")
#        output = pack2D(output,vals_vertex,"Vertex_tracksSize","n_pvs")
        
        output = packdistflat(output,vals_jet,"pt","Jet_")
        output = packdistflat(output,vals_jet,"eta","Jet_")
        output = packdistflat(output,vals_jet,"phi","Jet_")
        output = packdistflat(output,vals_nsub,"tau21","")
        output = packdistflat(output,vals_nsub,"tau32","")
        output = packdistflat(output,vals_fatjet,"pt","FatJet_")
        output = packdistflat(output,vals_fatjet,"eta","FatJet_")
        output = packdistflat(output,vals_fatjet,"phi","FatJet_")
        #output = packdistflat(output,vals_refatjet,"pt","reFatJet_")
        #output = packdistflat(output,vals_refatjet,"eta","reFatJet_")
        #output = packdistflat(output,vals_refatjet,"phi","reFatJet_")
        output = packdistflat(output,vals_tracks,"pt","PFcand_")
        output = packdistflat(output,vals_tracks,"eta","PFcand_")
        output = packdistflat(output,vals_tracks,"phi","PFcand_")
        output = packdist(output,vals,"FatJet_ncount30")
        output = packdist(output,vals,"FatJet_ncount50")
        output = packdist(output,vals,"FatJet_ncount100")
        output = packdist(output,vals,"FatJet_ncount150")
        output = packdist(output,vals,"FatJet_ncount200")
        output = packdist(output,vals,"FatJet_ncount250")
        output = packdist(output,vals,"FatJet_ncount300")
        output = packdist(output,valsx,"FatJet_nconst")
        output = packdist(output,valsx,"PFcand_ncount0")
        output = packdist(output,valsx,"PFcand_ncount50")
        output = packdist(output,valsx,"PFcand_ncount60")
        output = packdist(output,valsx,"PFcand_ncount70")
        output = packdist(output,valsx,"PFcand_ncount75")
        output = packdist(output,valsx,"PFcand_ncount80")
        output = packdist(output,valsx,"PFcand_ncount90")
        output = packdist(output,valsx,"PFcand_ncount100")
        output = packdist(output,valsx,"PFcand_ncount150")
        output = packdist(output,valsx,"PFcand_ncount200")
        output = packdist(output,valsx,"PFcand_ncount300")

        output = packdist_fjn1(output,vals_fj,"FatJet_ncount30")
        output = packdist_fjn1(output,vals_fj,"FatJet_ncount50")
        output = packdist_fjn1(output,vals_fj,"FatJet_ncount100")
        output = packdist_fjn1(output,vals_fj,"FatJet_ncount150")
        output = packdist_fjn1(output,vals_fj,"FatJet_ncount200")
        output = packdist_fjn1(output,vals_fj,"FatJet_ncount250")
        output = packdist_fjn1(output,vals_fj,"FatJet_ncount300")
        

        return output

    def postprocess(self, accumulator):
        return accumulator


# https://github.com/scikit-hep/uproot4/issues/122
uproot.open.defaults["xrootd_handler"] = uproot.source.xrootd.MultithreadedXRootDSource


fin = "HT2000"
batch = 0
signal=False
runInteractive=False
if len(sys.argv) >= 2:
  fin = sys.argv[1]
#fin = "sig400"
if len(sys.argv) >= 3:
  batch = int(sys.argv[2])
if "HT" in fin:
  fs = np.loadtxt("rootfiles/%sv2.txt"%(fin),dtype=str)
  start = 100*batch
  end = 100*(batch+1)
  if (end > len(fs)):
    fs = fs[start:]
  else:
    fs=fs[start:end]
  fileset = {
           #fin : ["root://xrootd.cmsaf.mit.edu://store/user/paus/nanosc/E03/%s"%(f) for f in fs],
           fin : ["root://cmseos.fnal.gov//store/group/lpcsuep/Scouting/QCDv3/E03/%s/%s"%(fin,f) for f in fs],
           #fin: ['root://cmseos.fnal.gov//store/group/lpcsuep/Scouting/QCDv2/HT2000/4C832A72-AF24-D045-ACE7-67DFC5D01F90.root']
  }
elif "Run" in fin:
  #Runs = ["RunA","RunB","RunC"]
  fs = np.loadtxt("rootfiles/Data%s.txt"%(fin),dtype=str)
  fs=fs[10*batch:10*(batch+1)]
  fileset = {
            fin:["root://cmseos.fnal.gov//store/group/lpcsuep/Scouting/Data/%s/%s"%(fin,f) for f in fs]
  }  
elif "Trigger" in fin:
  #Runs = ["RunA","RunB","RunC"]
  #runInteractive=True
  fs = np.loadtxt("rootfiles/%s.txt"%(fin),dtype=str)
  fs=fs[10*batch:10*(batch+1)]
  fileset = {
            fin:["root://cmseos.fnal.gov//store/group/lpcsuep/Scouting/Data/ScoutingPFCommissioning+Run2018A-v1+RAW/%s"%(f) for f in fs]
  }  
else:
  signal=True
  runInteractive=True
  decays = ["darkPho","darkPhoHad","generic"]
  fileset = {
            fin:["root://cmseos.fnal.gov//store/group/lpcsuep/Scouting/Signal/%s_%s_PU.root"%(fin,decays[batch])]
            #fin:["root://cmseos.fnal.gov//store/group/lpcsuep/Scouting/Signal/%s_%s_vertexgen.root"%(fin,decays[batch])]
  }  


if __name__ == "__main__":
    tic = time.time()
    #print(sys.argv)
    #dask.config.set({"distributed.scheduler.worker-ttl": "10min"})

    #cluster = LPCCondorCluster(
    #      memory="8GB",
    #)
    # minimum > 0: https://github.com/CoffeaTeam/coffea/issues/465
    #cluster.adapt(minimum=1, maximum=10)
    #client = Client(cluster)

    exe_args = {
        #"client": client,
        "savemetrics": True,
        "schema": BaseSchema, #nanoevents.NanoAODSchema,
        #"align_clusters": True,
    }

    proc = MyProcessor()

    print("Waiting for at least one worker...")
    #client.wait_for_workers(1)
    print("running %s %s"%(fin,batch))
    if(runInteractive):
      out = processor.run_uproot_job(
        fileset,
        treename="mmtree/tree",
        processor_instance=proc,
        executor=processor.iterative_executor,
        executor_args={
            "schema": BaseSchema,
        },
       # maxchunks=4,
      )
      print(out)
    else:
      out,metrics = processor.run_uproot_job(
          fileset,
          treename="mmtree/tree",
          processor_instance=proc,
          executor=processor.dask_executor,
          executor_args=exe_args,
          #dynamic_chunksize= {"memory":2048},
          chunksize= 10000,
          # remove this to run on the whole fileset:
          #maxchunks=10,
        #executor=processor.iterative_executor,
        #executor_args={
        #    "schema": BaseSchema,
        #},
      )

      elapsed = time.time() - tic
      print(f"Output: {out}")
      print(f"Metrics: {metrics}")
      print(f"Finished in {elapsed:.1f}s")
      print(f"Events/s: {metrics['entries'] / elapsed:.0f}")

    with open("outhists/myhistos_%s_%s.p"%(fin,batch), "wb") as pkl_file:
        pickle.dump(out, pkl_file)
