from argparse import Namespace
from collections import deque
from copy import deepcopy
from functools import partial
from typing import Deque, List, MutableSequence, Sequence, Union

import audio_classifier.common.feature_engineering.pool as feature_pool
import audio_classifier.common.feature_engineering.skm_proj as feature_skm_proj
import audio_classifier.common.preprocessing.spectrogram.reshape as spec_reshape
import audio_classifier.common.preprocessing.spectrogram.transform as spec_transform
import audio_classifier.config.feature_engineering.pool as conf_pool
import audio_classifier.config.preprocessing.reshape as conf_reshape
import audio_classifier.config.preprocessing.spec as conf_spec
import audio_classifier.train.collate.augment.sound_wave as collate_augment_sound_wave
import audio_classifier.train.collate.base as collate_base
import audio_classifier.train.collate.feature_engineering.pool as collate_pool
import audio_classifier.train.collate.feature_engineering.skm as collate_skm
import audio_classifier.train.collate.preprocessing.spectrogram.reshape as collate_reshape
import audio_classifier.train.collate.preprocessing.spectrogram.transform as collate_transform
import audio_classifier.train.config.alg as conf_alg
import audio_classifier.train.config.augment as conf_augment
import audio_classifier.train.config.dataset as conf_dataset
import audio_classifier.train.config.loader as conf_loader
import audio_classifier.train.data.dataset.base as dataset_base
import audio_classifier.train.data.dataset.utils.batch as batch_utils
import librosa.core as rosa_core
import numpy as np
from sklearn.base import ClassifierMixin
from sklearn.decomposition import PCA
from sklearn.pipeline import Pipeline
from sklearn.svm import SVC
from sklearn_plugins.cluster.spherical_kmeans import SphericalKMeans
from torch.utils.data.dataloader import DataLoader
from torch.utils.data.dataset import Dataset
from yellowbrick_plugins.cluster.elbow import SphericalKElbowVisualizer

from ..train import train_common
from ..train.classification import classify_common
from ..train.feature_engineering import feature_common

MetaDataType = train_common.MetaDataType
CollateFuncType = train_common.CollateFuncType


class BiasVarianceResultBase:
    train_accs: MutableSequence[float]
    val_accs: MutableSequence[float]
    test_accs: MutableSequence[float]
    skms: MutableSequence[Sequence[SphericalKMeans]]
    classifiers: MutableSequence[Union[Pipeline, ClassifierMixin]]

    def __init__(self) -> None:
        self.train_accs = list()
        self.val_accs = list()
        self.test_accs = list()
        self.skms = list()
        self.classifiers = list()


class BiasVarianceResult(BiasVarianceResultBase):
    k_min: int
    k_max: int
    k_step: int
    k_vals: MutableSequence[Sequence[int]]
    k_scores: MutableSequence[Sequence[Sequence[float]]]

    def __init__(self, k_min: int, k_max: int, k_step: int) -> None:
        super().__init__()
        self.k_min = k_min
        self.k_max = k_max
        self.k_step = k_step
        self.k_vals = list()
        self.k_scores = list()


class BiasVarianceFixKResult(BiasVarianceResultBase):
    k_vals: Sequence[int]

    def __init__(self, k_vals: Sequence[int]):
        super().__init__()
        self.k_vals = deepcopy(k_vals)


class BiasVarianceConfigBase:
    dataset_config: conf_dataset.PreSplitFoldDatasetConfig
    sound_wave_augment_config: conf_augment.SoundWaveAugmentConfig
    mel_spec_config: conf_spec.MelSpecConfig
    reshape_config: conf_reshape.ReshapeConfig
    skm_config: conf_alg.SKMConfig
    pca_config: conf_alg.PCAConfig
    svc_config: conf_alg.SVCConfig
    pool_config: conf_pool.PoolConfig
    loader_config: conf_loader.LoaderConfig
    test_audio_path: str
    export_path: str
    export_filename: str

    def __init__(self, argv: Namespace):
        dataset_config_path: str = argv.dataset_config_path
        sound_wave_augment_config_path: str = argv.sound_wave_augment_config_path
        spec_config_path: str = argv.spec_config_path
        reshape_config_path: str = argv.reshape_config_path
        skm_config_path: str = argv.skm_config_path
        pool_config_path: str = argv.pool_config_path
        pca_config_path: str = argv.pca_config_path
        svc_config_path: str = argv.svc_config_path
        loader_config_path: str = argv.loader_config_path
        self.dataset_config = conf_dataset.get_dataset_config_from_json(
            dataset_config_path, argv, conf_dataset.PreSplitFoldDatasetConfig)
        self.sound_wave_augment_config = conf_augment.get_augment_config_from_json(
            sound_wave_augment_config_path,
            conf_augment.SoundWaveAugmentConfig)
        self.mel_spec_config = conf_spec.get_spec_config_from_json(
            spec_config_path, conf_spec.MelSpecConfig)
        self.reshape_config = conf_reshape.get_reshape_config_from_json(
            reshape_config_path)
        self.skm_config = conf_alg.get_alg_config_from_json(
            skm_config_path, conf_alg.SKMConfig)
        self.pca_config = conf_alg.get_alg_config_from_json(
            pca_config_path, conf_alg.PCAConfig)
        self.svc_config = conf_alg.get_alg_config_from_json(
            svc_config_path, conf_alg.SVCConfig)
        self.pool_config = conf_pool.get_pool_config_from_json(
            pool_config_path)
        self.loader_config = conf_loader.get_loader_config_from_json(
            loader_config_path)
        self.test_audio_path = argv.test_audio_path
        self.export_path = argv.export_path
        self.export_filename = argv.export_filename


def generate_fold_datasets(
        configs: BiasVarianceConfigBase,
        metadata: MetaDataType) -> List[dataset_base.FolderDataset]:
    datasets: List[dataset_base.FolderDataset] = list()
    for curr_fold in range(configs.dataset_config.k_folds):
        curr_dataset: dataset_base.FolderDataset = train_common._sub_dataset_generator(
            curr_fold=curr_fold,
            dataset_config=configs.dataset_config,
            spec_config=configs.mel_spec_config,
            metadata=metadata)
        datasets.append(curr_dataset)
    return datasets


class BiasVarianceConfig(BiasVarianceConfigBase):
    k_min: int
    k_max: int
    k_step: int

    def __init__(self, argv: Namespace):
        super().__init__(argv)
        self.k_min = argv.k_min
        self.k_max = argv.k_max
        self.k_step = argv.k_step


class BiasVarianceFixKConfig(BiasVarianceConfigBase):
    k_vals: List[int]

    def __init__(self, argv: Namespace):
        super().__init__(argv)
        self.k_vals = argv.k_vals


def try_fit_skms(dataset: Dataset, configs: BiasVarianceConfig):
    collate_func: CollateFuncType = collate_base.EnsembleCollateFunction(
        collate_funcs=[
            partial(collate_transform.mel_spectrogram_collate,
                    config=configs.mel_spec_config),
            partial(collate_reshape.slice_flatten_collate,
                    config=configs.reshape_config)
        ])
    # load and preprocess incoming audio
    loader = DataLoader(dataset=dataset,
                        collate_fn=collate_func,
                        num_workers=configs.loader_config.num_workers,
                        batch_size=configs.loader_config.batch_size)
    batches_tmp: Deque[Sequence[Sequence]] = deque()
    np.seterr(divide="ignore")
    for batch in loader:
        batches_tmp.append(batch)
    np.seterr(divide="ignore")
    filenames, flat_slices, sample_freqs, sample_times, labels = batch_utils.combine_batches(
        batches_tmp)
    # the actual data used to fit skm
    train = feature_common.SliceDataset(filenames=filenames,
                                        flat_slices=flat_slices,
                                        sample_freqs=sample_freqs,
                                        sample_times=sample_times,
                                        labels=labels)
    slices, labels = feature_common.convert_to_ndarray(slice_dataset=train)
    unique_labels: np.ndarray = np.unique(labels)
    skms: List[SphericalKMeans] = list()
    k_vals: List[int] = list()
    k_scores: List[Sequence[float]] = list()
    for curr_label in unique_labels:
        skm = SphericalKMeans(n_components=configs.skm_config.n_components,
                              normalize=configs.skm_config.normalize,
                              standardize=configs.skm_config.standardize,
                              whiten=configs.skm_config.whiten,
                              copy=True,
                              max_iter=10000)
        # identify optimal k
        visualizer = SphericalKElbowVisualizer(estimator=skm,
                                               k=range(configs.k_min,
                                                       configs.k_max,
                                                       configs.k_step),
                                               locate_elbow=True)
        visualizer.fit(slices)
        k_val: Union[int, None] = visualizer.elbow_value_
        if k_val is None:
            k_scores.append(list())
            k_vals.append(-1)
            continue
        k_scores.append(visualizer.k_scores_)
        k_vals.append(k_val)
        # train skm with k
        skm = skm = SphericalKMeans(
            n_clusters=k_val,
            n_components=configs.skm_config.n_components,
            normalize=configs.skm_config.normalize,
            standardize=configs.skm_config.standardize,
            whiten=configs.skm_config.whiten,
            copy=True,
            max_iter=10000)
        skm.fit(slices)
        skms.append(skm)
    return skms, k_vals, k_scores


def fit_skms(dataset: Dataset, configs: BiasVarianceFixKConfig):
    collate_func: CollateFuncType = collate_base.EnsembleCollateFunction(
        collate_funcs=[
            partial(collate_transform.mel_spectrogram_collate,
                    config=configs.mel_spec_config),
            partial(collate_reshape.slice_flatten_collate,
                    config=configs.reshape_config)
        ])
    # load and preprocess incoming audio
    loader = DataLoader(dataset=dataset,
                        collate_fn=collate_func,
                        num_workers=configs.loader_config.num_workers,
                        batch_size=configs.loader_config.batch_size)
    batches_tmp: Deque[Sequence[Sequence]] = deque()
    np.seterr(divide="ignore")
    for batch in loader:
        batches_tmp.append(batch)
    np.seterr(divide="ignore")
    filenames, flat_slices, sample_freqs, sample_times, labels = batch_utils.combine_batches(
        batches_tmp)
    # the actual data used to fit skm
    train = feature_common.SliceDataset(filenames=filenames,
                                        flat_slices=flat_slices,
                                        sample_freqs=sample_freqs,
                                        sample_times=sample_times,
                                        labels=labels)
    slices, labels = feature_common.convert_to_ndarray(slice_dataset=train)
    unique_labels: np.ndarray = np.unique(labels)
    skms: List[SphericalKMeans] = list()
    for curr_label, k_val in zip(unique_labels, configs.k_vals):
        # train skm with k
        skm = skm = SphericalKMeans(
            n_clusters=k_val,
            n_components=configs.skm_config.n_components,
            normalize=configs.skm_config.normalize,
            standardize=configs.skm_config.standardize,
            whiten=configs.skm_config.whiten,
            copy=True,
            max_iter=10000)
        skm.fit(slices)
        skms.append(skm)
    return skms


def train_classifier(dataset: Dataset, skms: Sequence[SphericalKMeans],
                     configs: BiasVarianceConfigBase):
    collate_func: CollateFuncType = collate_base.EnsembleCollateFunction(
        collate_funcs=[
            partial(collate_augment_sound_wave.add_white_noise_collate,
                    config=configs.sound_wave_augment_config),
            partial(collate_transform.mel_spectrogram_collate,
                    config=configs.mel_spec_config),
            partial(collate_reshape.slice_flatten_collate,
                    config=configs.reshape_config),
            partial(collate_skm.skm_skl_proj_collate, skms=skms),
            partial(collate_pool.pool_collate,
                    pool_func=feature_pool.MeanStdPool(),
                    pool_config=configs.pool_config)
        ])
    # load and preprocess incoming audio
    loader = DataLoader(dataset=dataset,
                        collate_fn=collate_func,
                        num_workers=configs.loader_config.num_workers,
                        batch_size=configs.loader_config.batch_size)
    batches_tmp: Deque[Sequence[Sequence]] = deque()
    np.seterr(divide="ignore")
    for batch in loader:
        batches_tmp.append(batch)
    np.seterr(divide="ignore")
    filenames, all_file_spec_projs, sample_freqs, sample_times, labels = batch_utils.combine_batches(
        batches_tmp)
    proj_dataset = classify_common.ProjDataset(
        filenames=filenames,
        all_file_spec_projs=all_file_spec_projs,
        sample_freqs=sample_freqs,
        sample_times=sample_times,
        labels=labels)
    train_slices, train_labels = classify_common.convert_to_ndarray(
        all_file_spec_projs=proj_dataset.all_file_spec_projs,
        labels=proj_dataset.labels)
    pca = PCA(n_components=configs.pca_config.n_components,
              whiten=configs.pca_config.whiten,
              copy=True)
    svc = SVC(C=configs.svc_config.C,
              kernel=configs.svc_config.kernel,
              degree=configs.svc_config.degree,
              gamma=configs.svc_config.gamma,
              coef0=configs.svc_config.coef0)
    pca_svc = Pipeline(steps=[("pca", pca), ("svc", svc)])
    pca_svc.fit(train_slices, train_labels)
    train_acc: float = pca_svc.score(train_slices, train_labels)
    return pca_svc, train_acc


def val_classifier(dataset: Dataset, skms: Sequence[SphericalKMeans],
                   classifier: Pipeline, configs: BiasVarianceConfigBase):
    collate_func: CollateFuncType = collate_base.EnsembleCollateFunction(
        collate_funcs=[
            partial(collate_transform.mel_spectrogram_collate,
                    config=configs.mel_spec_config),
            partial(collate_reshape.slice_flatten_collate,
                    config=configs.reshape_config),
            partial(collate_skm.skm_skl_proj_collate, skms=skms),
            partial(collate_pool.pool_collate,
                    pool_func=feature_pool.MeanStdPool(),
                    pool_config=configs.pool_config)
        ])
    # load and preprocess incoming audio
    loader = DataLoader(dataset=dataset,
                        collate_fn=collate_func,
                        num_workers=configs.loader_config.num_workers,
                        batch_size=configs.loader_config.batch_size)
    batches_tmp: Deque[Sequence[Sequence]] = deque()
    np.seterr(divide="ignore")
    for batch in loader:
        batches_tmp.append(batch)
    np.seterr(divide="ignore")
    filenames, all_file_spec_projs, sample_freqs, sample_times, labels = batch_utils.combine_batches(
        batches_tmp)
    proj_dataset = classify_common.ProjDataset(
        filenames=filenames,
        all_file_spec_projs=all_file_spec_projs,
        sample_freqs=sample_freqs,
        sample_times=sample_times,
        labels=labels)
    val_slices, val_labels = classify_common.convert_to_ndarray(
        all_file_spec_projs=proj_dataset.all_file_spec_projs,
        labels=proj_dataset.labels)
    val_acc: float = classifier.score(val_slices, val_labels)
    return val_acc


def infer_single_audio(skms: Sequence[SphericalKMeans], classifier: Pipeline,
                       configs: BiasVarianceConfigBase):
    sound_wave, _ = rosa_core.load(path=configs.test_audio_path,
                                   sr=configs.mel_spec_config.sample_rate,
                                   mono=True)
    mel_spec, mel_freq, mel_time = spec_transform.transform_mel_spectrogram(
        sound_wave=sound_wave,
        sample_rate=configs.mel_spec_config.sample_rate,
        n_fft=configs.mel_spec_config.n_fft,
        n_mels=configs.mel_spec_config.n_mels,
        freq_min=configs.mel_spec_config.freq_min,
        freq_max=configs.mel_spec_config.freq_max,
        window_size=configs.mel_spec_config.window_size,
        hop_size=configs.mel_spec_config.hop_size,
        apply_log=configs.mel_spec_config.apply_log)
    slices: Sequence[np.ndarray] = spec_reshape.slice_spectrogram(
        spectrogram=mel_spec,
        slice_size=configs.reshape_config.slice_size,
        stride_size=configs.reshape_config.stride_size)
    flat_slices: Sequence[np.ndarray] = list()
    for slice in slices:
        flat: np.ndarray = spec_reshape.flatten_slice(slice, copy=True)
        flat_slices.append(flat)
    proj_slices: np.ndarray = feature_skm_proj.proj_skl_skm(flat_slices, skms)
    pool_slices: Sequence[np.ndarray] = feature_pool.apply_pool_func(
        spec_projs=proj_slices,
        pool_func=feature_pool.MeanStdPool(),
        pool_size=configs.pool_config.pool_size,
        stride_size=configs.pool_config.stride_size)
    pred = classifier.predict(np.asarray(pool_slices))
    # only have a single test audio
    res = np.bincount(pred, minlength=2)
    return res[0] / (res[0] + res[1])
