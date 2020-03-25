# -*- coding:utf-8 -*-

"""
Encode and emberder spectra.
"""

import os

import more_itertools
from pyteomics.mgf import read as mgf_read
from pyteomics.mzml import read as mzml_read
import json

import pandas as pd
import numpy as np
from numpy import concatenate
from numba import njit

import torch

from torch.utils import data
import torch.nn.functional as func
import torch.nn as nn

import faiss
import zlib
import ast

DEFAULT_IVF_NLIST = 100

class EncodeDataset:

    def __init__(self, input_specta_num):
        self.len = input_specta_num
        self.spectra_dataset = None

    def transform_mgf(self, prj, input_spctra_file, ref_spectra, miss_save_name):
        self.spectra_dataset = None
        print('Start spectra encoding ...')
        # 500 reference spectra
        reference_spectra = mgf_read(ref_spectra, convert_arrays=1)
        reference_intensity = np.array(
            [bin_spectrum(r.get('m/z array'), r.get('intensity array')) for r in reference_spectra])
        ndp_r_spec_list = caculate_r_spec(reference_intensity)

        self.ids_usi_dict, self.ids_list, self.usi_list, peakslist1, precursor_feature_list1 = {}, [], [], [], []
        ndp_spec_list = []
        i, j, k = 0, 0, 0
        charge_none_record, charge_none_list = 0, []
        encode_batch = 10000

        self.MGF = mgf_read(input_spctra_file, convert_arrays=1)
        if encode_batch > self.len:
            for s1 in self.MGF:

                # missing charge
                if s1.get('params').get('charge').__str__()[0] == "N":
                    charge_none_record += 1
                    spectrum_id = s1.get('params').get('title')
                    charge_none_list.append(spectrum_id)
                    k += 1
                    continue
                else:
                    # scan = s1.get('params').get('title').split(";")[-1].split("=")[-1]
                    scan = k
                    k += 1
                    spectra_file_name = str(input_spctra_file).split("/")[-1]
                    usi = "mzspec:" + str(prj) + ":" + spectra_file_name + ":index:" + str(scan)
                    ids = zlib.crc32(usi.encode('utf8'))
                    while self.ids_usi_dict.keys().__contains__(ids):
                        ids += 1
                    self.ids_usi_dict[ids] = usi
                    self.usi_list.append(usi)
                    self.ids_list.append(ids)
                    charge1 = int(s1.get('params').get('charge').__str__()[0])

                bin_s1 = bin_spectrum(s1.get('m/z array'), s1.get('intensity array'))
                # ndp_spec1 = np.math.sqrt(np.dot(bin_s1, bin_s1))
                ndp_spec1 = caculate_spec(bin_s1)
                peakslist1.append(bin_s1)
                ndp_spec_list.append(ndp_spec1)
                mass1 = float(s1.get('params').get('pepmass')[0])
                # charge1 = int(s1.get('params').get('charge').__str__()[0])
                precursor_feature1 = np.concatenate((self.gray_code(mass1), self.charge_to_one_hot(charge1)))
                precursor_feature_list1.append(precursor_feature1)

            tmp_precursor_feature_list1 = np.array(precursor_feature_list1)
            intensList01 = np.array(peakslist1)

            tmp_dplist01 = caculate_nornalization_dp(reference_intensity, ndp_r_spec_list, np.array(peakslist1),
                                                     np.array(ndp_spec_list))
            tmp01 = concatenate((tmp_dplist01, intensList01), axis=1)
            spectrum01 = concatenate((tmp01, tmp_precursor_feature_list1), axis=1)

            self.spectra_dataset = spectrum01
            peakslist1.clear()
            precursor_feature_list1.clear()
            ndp_spec_list.clear()
        else:
            for s1 in self.MGF:

                # missing charge
                if s1.get('params').get('charge').__str__()[0] == "N":
                    charge_none_record += 1
                    spectrum_id = s1.get('params').get('title')
                    charge_none_list.append(spectrum_id)
                    k += 1
                    continue
                else:
                    # scan = s1.get('params').get('title').split(";")[-1].split("=")[-1]
                    spectra_file_name = str(input_spctra_file).split("/")[-1]
                    scan = k
                    k += 1
                    usi = "mzspec:" + str(prj) + ":" + spectra_file_name + ":index:" + str(scan)
                    ids = zlib.crc32(usi.encode('utf8'))
                    while self.ids_usi_dict.keys().__contains__(ids):
                        ids += 1
                    self.ids_usi_dict[ids] = usi
                    self.usi_list.append(usi)
                    self.ids_list.append(ids)
                    charge1 = int(s1.get('params').get('charge').__str__()[0])

                bin_s1 = bin_spectrum(s1.get('m/z array'), s1.get('intensity array'))
                # ndp_spec1 = np.math.sqrt(np.dot(bin_s1, bin_s1))
                ndp_spec1 = caculate_spec(bin_s1)
                peakslist1.append(bin_s1)
                ndp_spec_list.append(ndp_spec1)
                mass1 = float(s1.get('params').get('pepmass')[0])
                # charge1 = int(s1.get('params').get('charge').__str__()[0])
                precursor_feature1 = np.concatenate((self.gray_code(mass1), self.charge_to_one_hot(charge1)))
                precursor_feature_list1.append(precursor_feature1)

                if len(peakslist1) == encode_batch:
                    i += 1
                    tmp_precursor_feature_list1 = np.array(precursor_feature_list1)
                    intensList01 = np.array(peakslist1)

                    tmp_dplist01 = caculate_nornalization_dp(reference_intensity, ndp_r_spec_list, np.array(peakslist1),
                                                             np.array(ndp_spec_list))

                    tmp01 = concatenate((tmp_dplist01, intensList01), axis=1)
                    spectrum01 = concatenate((tmp01, tmp_precursor_feature_list1), axis=1)

                    if i == 1:
                        self.spectra_dataset = spectrum01
                    else:
                        self.spectra_dataset = np.vstack((self.spectra_dataset, spectrum01))
                    peakslist1.clear()
                    precursor_feature_list1.clear()
                    ndp_spec_list.clear()
                    j = i * encode_batch

                elif (j + encode_batch + charge_none_record) > self.len:
                    if len(peakslist1) == self.len - j - charge_none_record:
                        tmp_precursor_feature_list1 = np.array(precursor_feature_list1)
                        intensList01 = np.array(peakslist1)

                        tmp_dplist01 = caculate_nornalization_dp(reference_intensity, ndp_r_spec_list,
                                                                 np.array(peakslist1), np.array(ndp_spec_list))

                        tmp01 = concatenate((tmp_dplist01, intensList01), axis=1)
                        spectrum01 = concatenate((tmp01, tmp_precursor_feature_list1), axis=1)

                        self.spectra_dataset = np.vstack((self.spectra_dataset, spectrum01))

                        peakslist1.clear()
                        precursor_feature_list1.clear()
                        ndp_spec_list.clear()
                    else:
                        continue

        if len(charge_none_list) > 0:
            np_mr = np.array(charge_none_list)
            df_mr = pd.DataFrame(np_mr, index=None, columns=None)
            df_mr.to_csv(miss_save_name, mode="a+", header=None, index=None)
            print("Charge Missing Number:{}".format(charge_none_record))
            del charge_none_list
        self.ids_usi_df = pd.DataFrame({"ids":self.ids_list, "usi":self.usi_list}, columns=["ids", "usi"])

        self.usi_list.clear()
        self.ids_list.clear()
        self.ids_usi_dict.clear()

        return self.ids_usi_df, self.spectra_dataset

    def transform_mzml(self, prj, input_spctra_file, ref_spectra, miss_save_name):
        from pyteomics.mzml import read as mzml_read
        self.spectra_dataset = None
        print('Start spectra encoding ...')
        # 500 reference spectra
        reference_spectra = mgf_read(ref_spectra, convert_arrays=1)
        reference_intensity = np.array(
            [bin_spectrum(r.get('m/z array'), r.get('intensity array')) for r in reference_spectra])
        ndp_r_spec_list = caculate_r_spec(reference_intensity)

        self.ids_usi_dict, self.ids_list, self.usi_list, peakslist1, precursor_feature_list1 = {}, [], [], [], []
        ndp_spec_list = []
        i, j, k = 0, 0, 0
        charge_none_record, charge_none_list = 0, []
        encode_batch = 10000

        self.MZML = mzml_read(input_spctra_file)
        if encode_batch > self.len:
            for s1 in self.MZML:

                # missing charge
                if s1.get("precursorList").get("precursor")[0].get("selectedIonList").get("selectedIon")[0].get(
                        "charge state").__str__()[0] == "N":
                    charge_none_record += 1
                    spectrum_id = s1.get("spectrum title")
                    charge_none_list.append(spectrum_id)
                    continue
                else:
                    scan = s1.get("spectrum title").split(",")[-1].split(":")[-1].strip("\"").split("=")[-1]
                    spectra_file_name = str(input_spctra_file).split("/")[-1]
                    usi = "mzspec:" + str(prj) + ":" + spectra_file_name + ":scan:" + str(scan)
                    # usi = str(prj) + ":" + str(input_spctra_file) + ":" + str(scan)

                    ids = zlib.crc32(usi.encode('utf8'))
                    while self.ids_usi_dict.keys().__contains__(ids):
                        ids += 1
                    self.ids_usi_dict[ids] = usi
                    self.usi_list.append(usi)
                    self.ids_list.append(ids)
                    charge1 = int(
                        s1.get("precursorList").get("precursor")[0].get("selectedIonList").get("selectedIon")[0].get(
                            "charge state").__str__()[0])

                bin_s1 = bin_spectrum(s1.get('m/z array'), s1.get('intensity array'))
                # ndp_spec1 = np.math.sqrt(np.dot(bin_s1, bin_s1))
                ndp_spec1 = caculate_spec(bin_s1)
                peakslist1.append(bin_s1)
                ndp_spec_list.append(ndp_spec1)
                mass1 = s1.get("precursorList").get("precursor")[0].get("selectedIonList").get("selectedIon")[0].get(
                    "selected ion m/z")
                # mass1 = float(s1.get('params').get('pepmass')[0])
                # charge1 = int(s1.get('params').get('charge').__str__()[0])
                precursor_feature1 = np.concatenate((self.gray_code(mass1), self.charge_to_one_hot(charge1)))
                precursor_feature_list1.append(precursor_feature1)

            tmp_precursor_feature_list1 = np.array(precursor_feature_list1)
            intensList01 = np.array(peakslist1)

            # calculate normalized dot product
            tmp_dplist01 = caculate_nornalization_dp(reference_intensity, ndp_r_spec_list, np.array(peakslist1),
                                                     np.array(ndp_spec_list))
            tmp01 = concatenate((tmp_dplist01, intensList01), axis=1)
            spectrum01 = concatenate((tmp01, tmp_precursor_feature_list1), axis=1)

            self.spectra_dataset = spectrum01
            peakslist1.clear()
            precursor_feature_list1.clear()
            ndp_spec_list.clear()
        else:
            for s1 in self.MZML:

                # missing charge
                if s1.get("precursorList").get("precursor")[0].get("selectedIonList").get("selectedIon")[0].get(
                        "charge state").__str__()[0] == "N":
                    charge_none_record += 1
                    spectrum_id = s1.get("spectrum title")
                    charge_none_list.append(spectrum_id)
                    continue
                else:
                    scan = s1.get("spectrum title").split(",")[-1].split(":")[-1].strip("\"").split("=")[-1]
                    spectra_file_name = str(input_spctra_file).split("/")[-1]
                    usi = "mzspec:" + str(prj) + ":" + spectra_file_name + ":scan:" + str(scan)
                    ids = zlib.crc32(usi.encode('utf8'))
                    while self.ids_usi_dict.keys().__contains__(ids):
                        ids += 1
                    self.ids_usi_dict[ids] = usi
                    self.usi_list.append(usi)
                    self.ids_list.append(ids)
                    charge1 = int(
                        s1.get("precursorList").get("precursor")[0].get("selectedIonList").get("selectedIon")[0].get(
                            "charge state").__str__()[0])

                bin_s1 = bin_spectrum(s1.get('m/z array'), s1.get('intensity array'))
                # ndp_spec1 = np.math.sqrt(np.dot(bin_s1, bin_s1))
                ndp_spec1 = caculate_spec(bin_s1)
                peakslist1.append(bin_s1)
                ndp_spec_list.append(ndp_spec1)
                mass1 = s1.get("precursorList").get("precursor")[0].get("selectedIonList").get("selectedIon")[0].get(
                    "selected ion m/z")
                # mass1 = float(s1.get('params').get('pepmass')[0])
                # charge1 = int(s1.get('params').get('charge').__str__()[0])
                precursor_feature1 = np.concatenate((self.gray_code(mass1), self.charge_to_one_hot(charge1)))
                precursor_feature_list1.append(precursor_feature1)

                if len(peakslist1) == encode_batch:
                    i += 1
                    tmp_precursor_feature_list1 = np.array(precursor_feature_list1)
                    intensList01 = np.array(peakslist1)

                    # calculate normorlized dot product
                    tmp_dplist01 = caculate_nornalization_dp(reference_intensity, ndp_r_spec_list, np.array(peakslist1),
                                                             np.array(ndp_spec_list))

                    tmp01 = concatenate((tmp_dplist01, intensList01), axis=1)
                    spectrum01 = concatenate((tmp01, tmp_precursor_feature_list1), axis=1)

                    if i == 1:
                        self.spectra_dataset = spectrum01
                    else:
                        self.spectra_dataset = np.vstack((self.spectra_dataset, spectrum01))
                    peakslist1.clear()
                    precursor_feature_list1.clear()
                    ndp_spec_list.clear()
                    j = i * encode_batch

                elif (j + encode_batch + charge_none_record) > self.len:
                    if len(peakslist1) == self.len - j - charge_none_record:
                        tmp_precursor_feature_list1 = np.array(precursor_feature_list1)
                        intensList01 = np.array(peakslist1)

                        tmp_dplist01 = caculate_nornalization_dp(reference_intensity, ndp_r_spec_list,
                                                                 np.array(peakslist1), np.array(ndp_spec_list))

                        tmp01 = concatenate((tmp_dplist01, intensList01), axis=1)
                        spectrum01 = concatenate((tmp01, tmp_precursor_feature_list1), axis=1)

                        self.spectra_dataset = np.vstack((self.spectra_dataset, spectrum01))

                        peakslist1.clear()
                        precursor_feature_list1.clear()
                        ndp_spec_list.clear()
                    else:
                        continue

        if len(charge_none_list) > 0:
            np_mr = np.array(charge_none_list)
            df_mr = pd.DataFrame(np_mr, index=None, columns=None)
            # df_mr.to_csv(miss_save_name)
            df_mr.to_csv(miss_save_name, mode="a+", header=None, index=None)
            print("Charge Missing Number:{}".format(charge_none_record))
            del charge_none_list

        self.ids_usi_df = pd.DataFrame({"ids": self.ids_list, "usi": self.usi_list}, columns=["ids", "usi"])

        self.usi_list.clear()
        self.ids_list.clear()
        self.ids_usi_dict.clear()

        return self.ids_usi_df, self.spectra_dataset

    def transform_json(self, input_spctra_file, ref_spectra, miss_save_name):
        self.spectra_dataset = None
        print('Start spectra encoding ...')
        # 500 reference spectra
        reference_spectra = mgf_read(ref_spectra, convert_arrays=1)
        reference_intensity = np.array(
            [bin_spectrum(r.get('m/z array'), r.get('intensity array')) for r in reference_spectra])
        ndp_r_spec_list = caculate_r_spec(reference_intensity)

        self.ids_usi_dict, self.ids_list, self.usi_list, peakslist1, precursor_feature_list1 = {}, [], [], [], []
        ndp_spec_list = []
        i, j, k = 0, 0, 0
        charge_none_record, charge_none_list = 0, []
        encode_batch = 10000

        if encode_batch > self.len:
            for s1 in input_spctra_file:

                # missing charge
                if s1.get("precursorCharge") == " ":
                    charge_none_record += 1
                    spectrum_id = s1.get("usi")
                    charge_none_list.append(spectrum_id)
                    continue
                else:
                    usi = s1.get("usi")
                    ids = zlib.crc32(usi.encode('utf8'))
                    while self.ids_usi_dict.keys().__contains__(ids):
                        ids += 1
                    self.ids_usi_dict[ids] = usi
                    self.usi_list.append(usi)
                    self.ids_list.append(ids)
                    charge1 = int(s1.get("precursorCharge"))

                bin_s1 = bin_spectrum(s1.get('masses'), s1.get('intensities'))
                # ndp_spec1 = np.math.sqrt(np.dot(bin_s1, bin_s1))
                ndp_spec1 = caculate_spec(bin_s1)
                peakslist1.append(bin_s1)
                ndp_spec_list.append(ndp_spec1)
                mass1 = s1.get("precursorMz")
                # mass1 = float(s1.get('params').get('pepmass')[0])
                # charge1 = int(s1.get('params').get('charge').__str__()[0])
                precursor_feature1 = np.concatenate((self.gray_code(mass1), self.charge_to_one_hot(charge1)))
                precursor_feature_list1.append(precursor_feature1)

            tmp_precursor_feature_list1 = np.array(precursor_feature_list1)
            intensList01 = np.array(peakslist1)

            # calculate normalized dot product
            tmp_dplist01 = caculate_nornalization_dp(reference_intensity, ndp_r_spec_list, np.array(peakslist1),
                                                     np.array(ndp_spec_list))
            tmp01 = concatenate((tmp_dplist01, intensList01), axis=1)
            spectrum01 = concatenate((tmp01, tmp_precursor_feature_list1), axis=1)

            self.spectra_dataset = spectrum01
            peakslist1.clear()
            precursor_feature_list1.clear()
            ndp_spec_list.clear()
        else:
            for s1 in input_spctra_file:

                # missing charge
                if s1.get("precursorCharge") == " ":
                    charge_none_record += 1
                    spectrum_id = s1.get("usi")
                    charge_none_list.append(spectrum_id)
                    continue
                else:
                    usi = s1.get("usi")
                    ids = zlib.crc32(usi.encode('utf8'))
                    while self.ids_usi_dict.keys().__contains__(ids):
                        ids += 1
                    self.ids_usi_dict[ids] = usi
                    self.usi_list.append(usi)
                    self.ids_list.append(ids)
                    charge1 = int(s1.get("precursorCharge"))

                bin_s1 = bin_spectrum(s1.get('masses'), s1.get('intensities'))
                # ndp_spec1 = np.math.sqrt(np.dot(bin_s1, bin_s1))
                ndp_spec1 = caculate_spec(bin_s1)
                peakslist1.append(bin_s1)
                ndp_spec_list.append(ndp_spec1)
                mass1 = s1.get("precursorMz")
                # mass1 = float(s1.get('params').get('pepmass')[0])
                # charge1 = int(s1.get('params').get('charge').__str__()[0])
                precursor_feature1 = np.concatenate((self.gray_code(mass1), self.charge_to_one_hot(charge1)))
                precursor_feature_list1.append(precursor_feature1)

                if len(peakslist1) == encode_batch:
                    i += 1
                    tmp_precursor_feature_list1 = np.array(precursor_feature_list1)
                    intensList01 = np.array(peakslist1)

                    # calculate normorlized dot product
                    tmp_dplist01 = caculate_nornalization_dp(reference_intensity, ndp_r_spec_list, np.array(peakslist1),
                                                             np.array(ndp_spec_list))

                    tmp01 = concatenate((tmp_dplist01, intensList01), axis=1)
                    spectrum01 = concatenate((tmp01, tmp_precursor_feature_list1), axis=1)

                    if i == 1:
                        self.spectra_dataset = spectrum01
                    else:
                        self.spectra_dataset = np.vstack((self.spectra_dataset, spectrum01))
                    peakslist1.clear()
                    precursor_feature_list1.clear()
                    ndp_spec_list.clear()
                    j = i * encode_batch

                elif (j + encode_batch + charge_none_record) > self.len:
                    if len(peakslist1) == self.len - j - charge_none_record:
                        tmp_precursor_feature_list1 = np.array(precursor_feature_list1)
                        intensList01 = np.array(peakslist1)

                        # Calculation of normalized dot product
                        tmp_dplist01 = caculate_nornalization_dp(reference_intensity, ndp_r_spec_list,
                                                                 np.array(peakslist1), np.array(ndp_spec_list))

                        tmp01 = concatenate((tmp_dplist01, intensList01), axis=1)
                        spectrum01 = concatenate((tmp01, tmp_precursor_feature_list1), axis=1)

                        self.spectra_dataset = np.vstack((self.spectra_dataset, spectrum01))

                        peakslist1.clear()
                        precursor_feature_list1.clear()
                        ndp_spec_list.clear()
                    else:
                        continue

        if len(charge_none_list) > 0:
            np_mr = np.array(charge_none_list)
            df_mr = pd.DataFrame(np_mr, index=None, columns=None)
            # df_mr.to_csv(miss_save_name)
            df_mr.to_csv(miss_save_name, mode="a+", header=None, index=None)
            print("Charge Missing Number:{}".format(charge_none_record))
            del charge_none_list

        self.ids_usi_df = pd.DataFrame({"ids": self.ids_list, "usi": self.usi_list}, columns=["ids", "usi"])

        self.usi_list.clear()
        self.ids_list.clear()
        self.ids_usi_dict.clear()

        return self.ids_usi_df, self.spectra_dataset

    def gray_code(self, number):
        """
        to get the gray code:\n
            1. a = get the num's binary form
            2. b = shift a one bit from left to right, put zero at the left position
            3. gray code = a xor b
            bin(num ^ (num >> 1))
        :param number:
        :return:np.array  gray code array for num
        """
        number = np.int(number)
        bit = 27
        shift = 1
        gray_code = np.binary_repr(np.bitwise_xor(number, np.right_shift(number, shift)), bit)
        return np.asarray(' '.join(gray_code).split(), dtype=float)

    def charge_to_one_hot(self, c: int):
        """
        encode charge with one-hot format for 1-7
        :param c:
        :return:
        """
        maximum_charge = 7
        charge = np.zeros(maximum_charge, dtype=float)
        if c > maximum_charge:
            c = maximum_charge
        charge[c - 1] = c
        return charge


@njit
def caculate_spec(bin_spec):
    ndp_spec1 = np.math.sqrt(np.dot(bin_spec, bin_spec))
    return ndp_spec1


@njit
def caculate_r_spec(reference_intensity):
    ndp_r_spec_list = np.zeros(500)
    for x in range(500):
        ndp_r_spec = np.math.sqrt(np.dot(reference_intensity[x], reference_intensity[x]))
        ndp_r_spec_list[x] = ndp_r_spec
    return ndp_r_spec_list


@njit
def get_bin_index(mz, min_mz, bin_size):
    relative_mz = mz - min_mz
    return max(0, int(np.floor(relative_mz / bin_size)))


@njit
def bin_spectrum(mz_array, intensity_array, max_mz=2500, min_mz=50.5, bin_size=1.0005079):
    """
    bin spectrum and this algorithm reference from 'https://github.com/dhmay/param-medic/blob/master/parammedic/binning.pyx'
    :param mz_array:
    :param intensity_array:
    :param max_mz:
    :param min_mz:
    :param bin_size:
    :return:
    """
    # key = mz_array.__str__()
    # if key in spectrum_dict.keys():  # use cache just take 4s
    #     # if False: use the old one may take 7s for 50
    #     return spectrum_dict[key]
    # else:
    nbins = int(float(max_mz - min_mz) / float(bin_size)) + 1
    results = np.zeros(nbins)

    for index in range(len(mz_array)):
        mz = mz_array[index]
        intensity = intensity_array[index]
        intensity = np.math.sqrt(intensity)
        if mz < min_mz or mz > max_mz:
            continue
        bin_index = get_bin_index(mz, min_mz, bin_size)

        if bin_index < 0 or bin_index > nbins - 1:
            continue
        if results[bin_index] == 0:
            results[bin_index] = intensity
        else:
            results[bin_index] += intensity

    intensity_sum = results.sum()

    if intensity_sum > 0:
        results /= intensity_sum
        # spectrum_dict[key] = results
    else:
        print('zero intensity found')
    return results


@njit
def caculate_nornalization_dp(reference, ndp_r_spec_list, bin_spectra, ndp_bin_sp):
    ndp_r_spec_list = ndp_r_spec_list.reshape(ndp_r_spec_list.shape[0], 1)
    ndp_bin_sp = ndp_bin_sp.reshape(ndp_bin_sp.shape[0], 1)
    tmp_dp_list = np.dot(bin_spectra, np.transpose(reference))
    dvi = np.dot(ndp_bin_sp, np.transpose(ndp_r_spec_list))
    result = tmp_dp_list / dvi
    return result


class SiameseNetwork2(nn.Module):

    def __init__(self):
        super(SiameseNetwork2, self).__init__()

        self.fc1_1 = nn.Linear(34, 32)
        self.fc1_2 = nn.Linear(32, 5)

        self.cnn11 = nn.Conv1d(1, 30, 3)
        self.maxpool11 = nn.MaxPool1d(2)

        self.cnn21 = nn.Conv1d(1, 30, 3)
        self.maxpool21 = nn.MaxPool1d(2)
        self.cnn22 = nn.Conv1d(30, 30, 3)
        self.maxpool22 = nn.MaxPool1d(2)

        self.fc2 = nn.Linear(25775, 32)

    def forward_once(self, pre_info, frag_info, ref_spec_info):
        pre_info = self.fc1_1(pre_info)
        pre_info = func.selu(pre_info)
        pre_info = self.fc1_2(pre_info)
        pre_info = func.selu(pre_info)
        pre_info = pre_info.view(pre_info.size(0), -1)

        frag_info = self.cnn21(frag_info)
        frag_info = func.selu(frag_info)
        frag_info = self.maxpool21(frag_info)
        frag_info = func.selu(frag_info)
        frag_info = self.cnn22(frag_info)
        frag_info = func.selu(frag_info)
        frag_info = self.maxpool22(frag_info)
        frag_info = func.selu(frag_info)
        frag_info = frag_info.view(frag_info.size(0), -1)

        ref_spec_info = self.cnn11(ref_spec_info)
        ref_spec_info = func.selu(ref_spec_info)
        ref_spec_info = self.maxpool11(ref_spec_info)
        ref_spec_info = func.selu(ref_spec_info)
        ref_spec_info = ref_spec_info.view(ref_spec_info.size(0), -1)

        output = torch.cat((pre_info, frag_info, ref_spec_info), 1)
        output = self.fc2(output)
        return output

    def forward(self, spectrum01, spectrum02):
        spectrum01 = spectrum01.reshape(spectrum01.shape[0], 1, spectrum01.shape[1])
        spectrum02 = spectrum02.reshape(spectrum02.shape[0], 1, spectrum02.shape[1])

        input1_1 = spectrum01[:, :, :500]
        input1_2 = spectrum01[:, :, 500:2949]
        input1_3 = spectrum01[:, :, 2949:]

        input2_1 = spectrum02[:, :, :500]
        input2_2 = spectrum02[:, :, 500:2949]
        input2_3 = spectrum02[:, :, 2949:]

        refSpecInfo1, fragInfo1, preInfo1 = input1_3.cuda(), input1_2.cuda(), input1_1.cuda()
        refSpecInfo2, fragInfo2, preInfo2 = input2_3.cuda(), input2_2.cuda(), input2_1.cuda()

        output01 = self.forward_once(refSpecInfo1, fragInfo1, preInfo1)
        output02 = self.forward_once(refSpecInfo2, fragInfo2, preInfo2)

        return output01, output02


class LoadDataset(data.dataset.Dataset):
    def __init__(self, data):
        self.dataset = data

    def __getitem__(self, item):
        return self.dataset[item]

    def __len__(self):
        return self.dataset.shape[0]


class EmbedDataset:
    def __init__(self, model, ids_data, vstack_encoded_spectra, store_embed_file, use_gpu):
        self.ids_vstack_df = None
        self.out_list = []
        self.embedding_dataset(model, ids_data, vstack_encoded_spectra, store_embed_file, use_gpu)

    def get_data(self):
        return self.ids_vstack_df

    def embedding_dataset(self, model, ids_data, encoded_spectra_data, store_embed_file, use_gpu):

        if use_gpu is True:
            # for gpu
            batch = 1000
            net = torch.load(model)
        else:
            # for cpu
            batch = 1
            net = torch.load(model, map_location='cpu')


        dataset = LoadDataset(encoded_spectra_data)

        dataloader = data.DataLoader(dataset=dataset, batch_size=batch, shuffle=False, num_workers=1)

        print("Start spectra embedding ... ")
        for j, test_data in enumerate(dataloader, 0):

            spectrum01 = test_data.reshape(test_data.shape[0], 1, test_data.shape[1])

            input1_1 = spectrum01[:, :, :500]
            input1_2 = spectrum01[:, :, 500:2949]
            input1_3 = spectrum01[:, :, 2949:]

            if use_gpu is True:
                # for gpu
                refSpecInfo1, fragInfo1, preInfo1 = input1_3.cuda(), input1_2.cuda(), input1_1.cuda()
                output01 = net.forward_once(refSpecInfo1, fragInfo1, preInfo1)
                out1 = output01.cpu().detach().numpy()
            else:
                # for cpu
                output01 = net.forward_once(input1_3, input1_2, input1_1)
                out1 = output01.detach().numpy()[0]

            if j == 0:
                self.out_list = out1
            else:
                self.out_list = np.vstack((self.out_list, out1))

        vstack_data_df = pd.DataFrame({"embedded_spectra": self.out_list.tolist()})
        self.ids_vstack_df = pd.concat([ids_data, vstack_data_df], axis=1)
        self.ids_vstack_df.to_csv(store_embed_file, header=True, index=None, columns=["ids", "embedded_spectra"])


def encode_spectra(prj, input_file, reference_spectra,  **kw):
    """
    Encode spectra
    :param prj: ProteomeXchange project/dataset accession
    :param input: get .mgf/.mzML/.json file as input
    :param reference_spectra: get a .mgf file contained 500 spectra as reference spectra from normalized dot product calculation
    :param kw: miss_record, ids_usi_save_file, encoded_spectra_save_file
    :return: ids_usi data, encoded_spectra data
    """
    dirname, filename = os.path.split(os.path.abspath(input_file))
    if kw.keys().__contains__("miss_record"):
        miss_record = kw["miss_record"]
    else:
        miss_record = dirname + "/" + filename.strip((filename.split(".")[-1])).strip(".") + "_missing_c_record.txt"

    if kw.keys().__contains__("ids_usi_save_file"):
        ids_usi_save_file = kw["ids_usi_save_file"]
    else:
        ids_usi_save_file = dirname + "/" + filename.strip((filename.split(".")[-1])).strip(".") + "_ids_usi.txt"

    if kw.keys().__contains__("encoded_spectra_save_file"):
        encoded_spectra_save_file = kw["encoded_spectra_save_file"]
    else:
        encoded_spectra_save_file = dirname + "/" + filename.strip((filename.split(".")[-1])).strip(".") + "_encoded.npy"

    if str(input_file).endswith(".mgf"):
        spectra_num = more_itertools.ilen(mgf_read(input, convert_arrays=1))

        mgf_encoder = EncodeDataset(spectra_num)
        ids_usi_df, vstack_data = mgf_encoder.transform_mgf(prj, input_file, reference_spectra, miss_record)

        pd.DataFrame(ids_usi_df).to_csv(ids_usi_save_file, header=True, index=None)
        np.save(encoded_spectra_save_file, vstack_data)

        return ids_usi_df, vstack_data

    elif str(input_file).endswith(".mzML"):

        spectra_num = more_itertools.ilen(mzml_read(input_file))
        mzml_encoder = EncodeDataset(spectra_num)
        ids_usi_df, vstack_data = mzml_encoder.transform_mzml(prj, input_file, reference_spectra, miss_record)

        pd.DataFrame(ids_usi_df).to_csv(ids_usi_save_file, header=True, index=None)
        np.save(encoded_spectra_save_file, vstack_data)

        return ids_usi_df, vstack_data
    else:
        with open(input_file) as fh:
            spectra_json_file = [json.loads(line) for line in fh if line]
        spectra_num = len(spectra_json_file)
        json_encoder = EncodeDataset(spectra_num)
        ids_usi_df, vstack_data = json_encoder.transform_json(spectra_json_file, reference_spectra, miss_record)

        pd.DataFrame(ids_usi_df).to_csv(ids_usi_save_file, header=True, index=None)
        np.save(encoded_spectra_save_file, vstack_data)

        return ids_usi_df, vstack_data


def embed_spectra(model, ids_usi_data, vstack_encoded_spectra, output_embedd_file, **kwargs):
    """
    Embed spectra
    :param model:  .pkl format embedding model
    :param ids_usi_data: ids-usi dataframe data
    :param vstack_encoded_spectra: encoded spectra file for embedding
    :param kwargs: bool, default=False;
    :return: ids-embedded_spectra data
    """

    if kwargs.keys().__contains__("use_gpu"):
        use_gpu = kwargs["use_gpu"]
    else:
        use_gpu = False

    ids_data = ids_usi_data["ids"]

    ids_embedded_spectra = EmbedDataset(model, ids_data, vstack_encoded_spectra, output_embedd_file, use_gpu).get_data()

    print("Finish spectra embedding, save embedded spectra to " + output_embedd_file + "!")
    return ids_embedded_spectra


def encode_and_embed_spectra(model, prj, input_file, refrence_spectra, output_embedded_file):
    """

    :param model: .pkl format embedding model
    :param input: get .mgf or .mzML file as input
    :param refrence_spectra: refrence_spectra: get a .mgf file contained 500 spectra as referece spectra from normalized dot product calculation
    :param miss_record: record title of some spectra which loss charge attribute
    :param output_embedded_file: file to store the embedded data
    :param use_gpu: bool
    :return: embedded spectra 32d vector
    """

    ids_usi_df, vstack_encoded_spectra = encode_spectra(prj, input_file, refrence_spectra)
    ids_embedded_spectra = embed_spectra(model, ids_usi_df, vstack_encoded_spectra, output_embedded_file)

    return ids_embedded_spectra


class FaissWriteIndex:

    def __init__(self):
        self.tmp = None
        print("Initialized a faiss index class.")

    def create_index(self, ids_embedded_spectra, ids_save_file, output_path):
        """
        Create faiss indexIDMap index
        :param spectra_vectors: spectra embedded data
        :param usi_data: coresponding usi data
        :param output_path: output file path
        :return:
        """
        ids_data = ids_embedded_spectra["ids"].values
        spectra_vectors = ids_embedded_spectra["embedded_spectra"].values
        if type(spectra_vectors[0]) == type("test"):
            tmp_data = []
            for vec in spectra_vectors:
                tmp_data.append(ast.literal_eval(vec))
            tmp_spectra_vectors = np.vstack(tmp_data)
            tmp_data.clear()
        else:
            tmp_spectra_vectors = np.vstack(spectra_vectors)
        np.save(ids_save_file, ids_data)
        n_embedded_dim = tmp_spectra_vectors.shape[1]
        index = self.make_faiss_index_IDMap(n_embedded_dim)
        index.add_with_ids(tmp_spectra_vectors.astype('float32'), ids_data)
        self.write_faiss_index(index, output_path)

    def add_index(self, raw_index, raw_ids_file, new_ids_embedded_data, output_index_ids_file, output_index_file):
        """
        Add new_index data to a raw_index
        :param raw_index: Raw index file
        :param new_index: New index file
        :param new_usi_data: New index's corresponding usi data
        :param output_path: Output file path
        :return:
        """
        new_ids_data = new_ids_embedded_data["ids"].values.tolist()
        new_embedded_spectra = new_ids_embedded_data["embedded_spectra"]

        #Determine whether the new index is the same as the original index
        raw_ids_dict = dict.fromkeys(np.load(raw_ids_file).tolist(), [])
        update_new_ids = []
        update_id_bool = False
        for new_id in new_ids_data:
            print("new id:{}".format(new_id))
            tmp_id = new_id
            while raw_ids_dict.keys().__contains__(tmp_id):
                tmp_id += 1
            if tmp_id != new_id:
                update_id_bool = True
            update_new_ids.append(tmp_id)

        if update_id_bool is True:
            print("Need to update new sepctra list's ids, save updated ids to "+str(output_index_ids_file).strip(".npy") + "_new_spectra_updated_ids.npy.")
            np.save(str(output_index_ids_file).strip(".npy") + "_new_spectra_updated_ids.npy.", update_new_ids)
            # add index
            raw_index.add_with_ids(new_embedded_spectra.astype('float32'), np.array(update_new_ids))
            new_faiss_index_ids = np.load(raw_ids_file).tolist().extend(update_new_ids)
            np.save(output_index_ids_file, new_faiss_index_ids)
            self.write_faiss_index(raw_index, output_index_file)
        else:
            update_new_ids.clear()
            # add index
            raw_index.add_with_ids(new_embedded_spectra.astype('float32'), np.array(new_ids_data))
            new_faiss_index_ids = np.load(raw_ids_file).tolist().extend(new_ids_data)
            np.save(output_index_ids_file, new_faiss_index_ids)
            self.write_faiss_index(raw_index, output_index_file)

    def make_faiss_indexFlat(self, n_dimensions, index_type='flat'):
        """
        Make a fairly general-purpose FAISS index
        :param n_dimensions:
        :param index_type: Type of index to build: flat or ivfflat. ivfflat is much faster.
        :return:
        """
        print("Making index of type {}".format(index_type))
        if faiss.get_num_gpus():
            gpu_resources = faiss.StandardGpuResources()
            if index_type == 'flat':
                config = faiss.GpuIndexFlatConfig()
                index = faiss.GpuIndexFlatL2(gpu_resources, n_dimensions, config)
            elif index_type == 'ivfflat':
                config = faiss.GpuIndexIVFFlatConfig()
                index = faiss.GpuIndexIVFFlat(gpu_resources, n_dimensions, DEFAULT_IVF_NLIST, faiss.METRIC_L2, config)
            else:
                raise ValueError("Unknown index_type %s" % index_type)
        else:
            print("Using CPU.")
            if index_type == 'flat':
                index = faiss.IndexFlatL2(n_dimensions)
            elif index_type == 'ivfflat':
                quantizer = faiss.IndexFlatL2(n_dimensions)
                index = faiss.IndexIVFFlat(quantizer, n_dimensions, DEFAULT_IVF_NLIST, faiss.METRIC_L2)
            else:
                raise ValueError("Unknown index_type %s" % index_type)
        return index

    def make_faiss_index_IDMap(self, n_dimensions):
        """
        Make a fairly general-purpose FAISS index
        :param n_dimensions:
        :return:
        """
        print("Making index ： IDMap...")
        tmp_index = faiss.IndexFlatL2(n_dimensions)
        index = faiss.IndexIDMap(tmp_index)
        return index

    def write_faiss_index(self, index, out_filepath):
        """
        Save a FAISS index. If we're on GPU, have to convert to CPU index first
        :param index:
        :return:
        """
        if faiss.get_num_gpus():
            print("Converting index from GPU to CPU...")
            index = faiss.index_gpu_to_cpu(index)
        faiss.write_index(index, out_filepath)
        print("Wrote FAISS index to {}".format(out_filepath))

