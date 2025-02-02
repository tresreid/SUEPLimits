import awkward as ak
import numpy as np
import matplotlib.pyplot as plt
import uproot
from coffea.jetmet_tools import FactorizedJetCorrector, JetCorrectionUncertainty
from coffea.jetmet_tools import JECStack, CorrectedJetsFactory
from coffea.lookup_tools import extractor

#from coffea.analysis_tools import Weights


# register our candidate behaviors
from coffea.nanoevents.methods import candidate
ak.behavior.update(candidate.behavior)





def correctJets(vals_jet0,cache,era=18,datatype="MC",Run=""):
        if datatype == "Trigger":
          return vals_jet0
        #if datatype == "MC" and era==16:
        #  return vals_jet0
        ext_ak4 = extractor()
        if era==18:
          if Run != "":
            Run = "_Run%s"%Run
          jecdir = "Autumn18%s_V19_%s"%(Run,datatype)
          jerdir = "Autumn18_V7b_%s"%(datatype)
        elif era==17:
          if Run =="D" or Run =="E":
            Run = "DE"
          jecdir = "Fall17_17Nov2017%s_V32_%s"%(Run,datatype)
          jerdir = "Summer19UL17_JRV3_%s"%(datatype)
        elif era==16:
          if Run =="B" or Run =="C" or Run=="D":
            Run = "BCD"
          if Run =="E" or Run =="F":
            Run = "EF"
          if Run =="G" or Run =="H":
            Run = "GH"
          jecdir = "Summer16_07Aug2017%s_V11_%s"%(Run,datatype)
          jerdir = "Summer16_25nsV1b_MC"
          #jerdir = "Summer20UL16_JRV3_%s"%(datatype)
        else:
          jerdir = "Summer19UL%s_JRV3_%s"%(era,datatype)
        jecpath = "jetscale_corrections/20%s/"%(era)+jecdir
        jerpath = "jetresolution_corrections/20%s/"%(era)+jerdir
        ext_ak4.add_weight_sets([
            "* * systematics/" + jecpath+"_L1FastJet_AK4PF.jec.txt", #looks to be 0,
            "* * systematics/" + jecpath+"_L1RC_AK4PF.jec.txt", #needs area
            "* * systematics/" + jecpath+"_L2L3Residual_AK4PF.jec.txt",
            "* * systematics/" + jecpath+"_L2Relative_AK4PF.jec.txt",
            "* * systematics/" + jecpath+"_L3Absolute_AK4PF.jec.txt", #looks to be 1, no change
            "* * systematics/" + jecpath+"_Uncertainty_AK4PF.junc.txt",
       #     "* * systematics/" + jerpath+"_PtResolution_AK4PF.jr.txt",
       #     "* * systematics/" + jerpath+"_SF_AK4PF.jersf.txt",
        ])
        if "DATA" not in datatype:
        	ext_ak4.add_weight_sets([
            	"* * systematics/" + jerpath+"_PtResolution_AK4PF.jr.txt",
            	"* * systematics/" + jerpath+"_SF_AK4PF.jersf.txt",
        	])
        ext_ak4.finalize()

        jec_stack_names_ak4 = [
            jecdir + "_L1FastJet_AK4PF",
            jecdir + "_L2Relative_AK4PF",
            jecdir + "_L3Absolute_AK4PF",
            jecdir + "_Uncertainty_AK4PF",
        ]
        if(datatype=="DATA"):
          jec_stack_names_ak4 = [
            jecdir + "_L1RC_AK4PF",
            jecdir + "_L2L3Residual_AK4PF"
        ]+ jec_stack_names_ak4
        else:
          jec_stack_names_ak4 = [
            jerdir + "_PtResolution_AK4PF",
            jerdir + "_SF_AK4PF",
        ]+ jec_stack_names_ak4

        evaluator_ak4 = ext_ak4.make_evaluator()

        jec_inputs_ak4 = {name: evaluator_ak4[name] for name in jec_stack_names_ak4}
        jec_stack_ak4 = JECStack(jec_inputs_ak4)
        name_map = jec_stack_ak4.blank_name_map
        name_map['JetPt'] = 'pt'
        name_map['JetMass'] = 'mass'
        name_map['JetEta'] = 'eta'
        name_map['JetA'] = 'area'
        name_map['massRaw'] = 'mass_raw'
        name_map['ptRaw'] = 'pt_raw'
        name_map['ptGenJet'] = 'ptGen'
        name_map['Rho'] = 'rho'
        jet_factory = CorrectedJetsFactory(name_map, jec_stack_ak4)
        return jet_factory.build(vals_jet0, lazy_cache=cache)
def pileup_weight(puarray,systematics=0,era=18):
    if era == 18:
        f_MC = uproot.open("systematics/pileup/mcPileupUL2018.root")
        f_data = uproot.open("systematics/pileup/PileupHistogram-UL2018-100bins_withVar.root")
    elif era == 17:
        f_MC = uproot.open("systematics/pileup/mcPileupUL2017.root")
        f_data = uproot.open("systematics/pileup/PileupHistogram-UL2017-100bins_withVar.root")
    elif era == 16:
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
    #print("PU: ",weights)
    if systematics==0:
      return np.take(weights,puarray)
    elif systematics==1:
      return np.take(weights_plus,puarray)
    elif systematics==2:
      return np.take(weights_minus,puarray)
    else:
      return np.take(weights,puarray)
def PS_weight(array,PSSystematics):
	# central value (0 and 1 repeat) then isr hi, fsr hig isr low fsr low for reduced, then default then conservative. Take default values        
	if(PSSystematics==1): #isr hi
		pswgt = array["PSweights"][:,0] * array["PSweights"][:,6]
	elif(PSSystematics==2): # fsr hi
		pswgt = array["PSweights"][:,0] * array["PSweights"][:,7]
	if(PSSystematics==3): # isr low
		pswgt = array["PSweights"][:,0] * array["PSweights"][:,8]
	elif(PSSystematics==4): #fsr low
		pswgt = array["PSweights"][:,0] * array["PSweights"][:,9]
	else:
		pswgt =1 
	return pswgt
def higgs_reweight(gen_pt,higgsSystematics):
    bins = np.array([   0,  400,  450,  500,  550,  600,  650,  700,  750,  800,  850,
            900,  950, 1000, 1050, 1100, 1150, 1200, 1250, 15000])
    Higgs_factor = np.array([1.25, 1.25, 1.25, 1.25, 1.25, 1.24, 1.24, 1.24, 1.24, 1.24, 1.24,
           1.24, 1.24, 1.24, 1.24, 1.24, 1.24, 1.24, 1.24])
    up_factor   = np.array([1.092, 1.092, 1.089, 1.088, 1.088, 1.087, 1.087, 1.087, 1.087,
           1.087, 1.085, 1.086, 1.086, 1.086, 1.087, 1.087, 1.087, 1.086,
           1.086])
    down_factor = np.array([0.88, 0.88, 0.89, 0.89, 0.89, 0.89, 0.89, 0.89, 0.89, 0.89, 0.89,
           0.89, 0.89, 0.89, 0.89, 0.89, 0.88, 0.88, 0.88])

    vals = plt.hist(gen_pt, bins=bins)

    freqs = vals[0] * Higgs_factor
    ups   = freqs * up_factor
    downs = freqs * down_factor

    start = vals[0].sum()
    end = freqs.sum()
    factor = start/end

    freqs = freqs * factor
    ups = ups * factor
    downs = downs * factor

    higgs_weights = freqs / vals[0]
    higgs_weights_up = ups / vals[0]
    higgs_weights_down = downs / vals[0]

    gen_bin = np.digitize(gen_pt,bins)-1
    if higgsSystematics == 1:
         higgs_weight = higgs_weights_up[gen_bin]
    elif higgsSystematics == 2:
         higgs_weight = higgs_weights_down[gen_bin]
    else:
         higgs_weight = higgs_weights[gen_bin]
    #print(higgs_weight)
    #print(higgs_weights[gen_bin])
    #print(higgs_weights_up[gen_bin])
    #print(higgs_weights_down[gen_bin])
    return higgs_weight

def gettrigweights(htarray,systematics=0,era=18):
    bins, trigwgts, wgterr = np.loadtxt("systematics/triggers/trigger_systematics_20%s.txt"%(era), delimiter=",")
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
    return scaleFactor
def prefire_weight(array,systematics=0):
	if systematics == 1:
		prefire = array["prefireup"]
	elif systematics == 2:
		prefire = array["prefiredown"]
	else:
		prefire = array["prefire"]
	return prefire
def killTracks(tracks_cut0):
        np.random.seed(2022) #random seed to get repeatable results
        pt_bins = np.array([0.0,0.1,0.2,0.3,0.4,0.5,0.75,1,1.25,1.5,2.0,3,10,20,50])
        datascale =  np.loadtxt("systematics/triggers/track_datascaling_full_2018_pt.txt", delimiter=",")
        qcdscale =  np.loadtxt("systematics/triggers/track_offlinescaling_full_2018_pt.txt", delimiter=",")
        # if 5% chance to not reconstruct MC track in real data, then MC_off/Data_off = 1.05 -> more MC than DATA. Then ratio in scouting = (MC_off/Data_off)* (MC_s/MC_off)*(Data_off/Data_s) = 1.05 * QCDscale/datascale
        scaling = np.divide(qcdscale,datascale)
        scaling = np.append(scaling,scaling[-1])
        trackbin = np.digitize(ak.flatten(tracks_cut0["pt"]),pt_bins)-1
        #print(scaling)
        #print(trackbin)
        scale = np.take(scaling,trackbin)
        probs = ak.where(ak.flatten(tracks_cut0["pt"]) < 20,0.025*scale,0.01*scale) #5% if pt < 1, otherwise 2%.
        #probs = ak.where(ak.flatten(tracks_cut0["pt"]) < 20,0.05*scale,0.02*scale) #5% if pt < 1, otherwise 2%.
        #print(probs)
        #probs = ak.where(ak.flatten(tracks_cut0["pt"]) < 20,0.05,0.02) #5% if pt < 1, otherwise 2%.
        rands = np.random.rand(len(probs)) > probs
        trk_killer = ak.Array(ak.layout.ListOffsetArray64(tracks_cut0.layout.offsets, ak.layout.NumpyArray(rands)))
        tracks_cut0 = tracks_cut0[trk_killer]
        return tracks_cut0
def killTracksOffline(tracks_cut0):
    pt_bins = np.array([0.0,0.1,0.2,0.3,0.4,0.5,0.75,1,1.25,1.5,2.0,3,10,20,50])
    eta_bins = np.array(range(-250,275,25))/100.
    trackwgts = np.loadtxt("systematics/triggers/track_drop_full_2018.txt", delimiter=",")#.flatten()
    #print("Track wgt len:", len(trackwgts),len(trackwgts[7]))
    trackwgts = np.vstack((trackwgts,trackwgts[-1])) #repeat last bin for overflow
    #print("Track wgt len 2:",len(trackwgts),len(trackwgts[7]))
    trackwgts = trackwgts.flatten()
    #print(trackwgts)
    ptbin = np.digitize(ak.flatten(tracks_cut0["pt"]),pt_bins)-1
    #print(list(ptbin))
    #print(pt_bins,eta_bins)
    etabin = np.digitize(ak.flatten(tracks_cut0["eta"]),eta_bins)-1
    bins = np.add((ptbin)*(len(eta_bins)-1),etabin)
    #print("bins:",bins)
    probs = np.take(trackwgts,bins)
    #print(tracks_cut0["pt"])
    #print(tracks_cut0["eta"])
    #print(probs)
    rands = np.random.rand(len(probs)) < probs # keep track is less than probability
    trk_killer = ak.Array(ak.layout.ListOffsetArray64(tracks_cut0.layout.offsets, ak.layout.NumpyArray(rands)))
    tracks_cut0 = tracks_cut0[trk_killer]
    return tracks_cut0
def scaleTracksOffline(spherex):
    track_bins= np.array([  0.,   6.,  12.,  18.,  24.,  30.,  36.,  42.,  48.,  54.,  60.,
        66.,  72.,  78.,  84.,  90.,  96., 102., 108., 114., 120., 126.,
       132., 138., 144., 150., 156., 162., 168., 174., 180., 186., 192.,
       198., 204., 210., 216., 222., 228., 234., 240., 246., 252., 258.,
       264., 270., 276., 282., 288., 294., 300.])
    trackwgts = np.loadtxt("systematics/triggers/track_multiplicity_ratio_2018.txt", delimiter=",")#.flatten()
    #print(trackwgts)
    trackwgts[trackwgts == 0] = 0.12907325
    #trackwgts = np.vstack((trackwgts,trackwgts[-1])) #repeat last bin for overflow
    #trackwgts = trackwgts.flatten()
    trackbin = np.digitize(spherex["FatJet_nconst"],track_bins)-1
    #etabin = np.digitize(ak.flatten(tracks_cut0["eta"]),eta_bins)-1
    #bins = np.add((ptbin)*(len(eta_bins)-1),etabin)
    probs = np.take(trackwgts,trackbin)
    #print(trackbin)
    #print(spherex["FatJet_nconst"])
    
    #print(probs)
    #rands = np.random.rand(len(probs)) < probs # keep track is less than probability
    #trk_killer = ak.Array(ak.layout.ListOffsetArray64(tracks_cut0.layout.offsets, ak.layout.NumpyArray(rands)))
    #tracks_cut0 = tracks_cut0[trk_killer]
    spherex["wgt"] = spherex["wgt"] * 1/probs
    return spherex
def calculateHT(vals0,corrected_jets,AK4sys):
        print("calculating HT with systematic %s"%AK4sys)
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
        elif AK4sys ==3 :
                vals0['ht20'] = ak.sum(corrected_jets.JER.up["pt"][(corrected_jets["passId"] ==1) & (corrected_jets.JER.up["pt"] > 20)],axis=-1)
                vals0['ht30'] = ak.sum(corrected_jets.JER.up["pt"][(corrected_jets["passId"] ==1) & (corrected_jets.JER.up["pt"] > 30)],axis=-1)
                vals0['ht40'] = ak.sum(corrected_jets.JER.up["pt"][(corrected_jets["passId"] ==1) & (corrected_jets.JER.up["pt"] > 40)],axis=-1)
                vals0['ht50'] = ak.sum(corrected_jets.JER.up["pt"][(corrected_jets["passId"] ==1) & (corrected_jets.JER.up["pt"] > 50)],axis=-1)
        elif AK4sys ==4 :
                vals0['ht20'] = ak.sum(corrected_jets.JER.down["pt"][(corrected_jets["passId"] ==1) & (corrected_jets.JER.down["pt"] > 20)],axis=-1)
                vals0['ht30'] = ak.sum(corrected_jets.JER.down["pt"][(corrected_jets["passId"] ==1) & (corrected_jets.JER.down["pt"] > 30)],axis=-1)
                vals0['ht40'] = ak.sum(corrected_jets.JER.down["pt"][(corrected_jets["passId"] ==1) & (corrected_jets.JER.down["pt"] > 40)],axis=-1)
                vals0['ht50'] = ak.sum(corrected_jets.JER.down["pt"][(corrected_jets["passId"] ==1) & (corrected_jets.JER.down["pt"] > 50)],axis=-1)
        else:
                vals0['ht20'] = ak.sum(corrected_jets["pt"][(corrected_jets["passId"] ==1) & (corrected_jets["pt"] > 20)],axis=-1)
                vals0['ht30'] = ak.sum(corrected_jets["pt"][(corrected_jets["passId"] ==1) & (corrected_jets["pt"] > 30)],axis=-1)
                vals0['ht40'] = ak.sum(corrected_jets["pt"][(corrected_jets["passId"] ==1) & (corrected_jets["pt"] > 40)],axis=-1)
                vals0['ht50'] = ak.sum(corrected_jets["pt"][(corrected_jets["passId"] ==1) & (corrected_jets["pt"] > 50)],axis=-1)
        vals0['ht'] = vals0['ht30']
        return vals0

from coffea import lumi_tools

def applyGoldenJSON(era, events):
    if era == 16:
        LumiJSON = lumi_tools.LumiMask('systematics/GoldenJSON/Cert_271036-284044_13TeV_Legacy2016_Collisions16_JSON.txt')
    elif era == 17:
        LumiJSON = lumi_tools.LumiMask('systematics/GoldenJSON/Cert_294927-306462_13TeV_UL2017_Collisions17_GoldenJSON.txt')
    elif era == 18:
        LumiJSON = lumi_tools.LumiMask('systematics/GoldenJSON/Cert_314472-325175_13TeV_Legacy2018_Collisions18_JSON.txt')
    else:
        print('No era is defined. Please specify the year')

    events = events[LumiJSON(events.run, events.lumSec)]

    return events
