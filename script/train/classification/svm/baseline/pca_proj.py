import os
import sys
from argparse import Namespace
from functools import partial
from typing import List, Sequence

import audio_classifier.common.feature_engineering.pool as feature_pool
import audio_classifier.train.collate.base as collate_base
import audio_classifier.train.collate.feature_engineering.pool as collate_pool
import audio_classifier.train.collate.feature_engineering.skm as collate_skm
import audio_classifier.train.collate.preprocessing.spectrogram.reshape as collate_reshape
import audio_classifier.train.collate.preprocessing.spectrogram.transform as collate_transform
import script.train.common as script_common
import script.train.skl_loader.skm as skl_skm_laoder
from audio_classifier.train.data.dataset.composite import KFoldDatasetGenerator
from script.train.classification.svm import train_common
from script.train.classification.svm.baseline import train_pca_proj
from sklearn.svm import SVC
from sklearn_plugins.cluster.spherical_kmeans import SphericalKMeans

MetaDataType = script_common.MetaDataType
CollateFuncType = script_common.CollateFuncType


def main(args: List[str]):
    argv: Namespace = train_pca_proj.parse_args(args)
    skm_root_path: str = argv.skm_root_path
    val_fold_path_stub: str = "val_{:02d}"
    class_skm_path_stub: str = "class_{:02d}/model.pkl"
    export_path: str = argv.export_path
    os.makedirs(export_path, exist_ok=True)
    dataset_config, mel_spec_config, reshape_config, pool_config, pca_config, svc_config, loader_config = train_pca_proj.get_config(
        argv=argv)
    metadata: MetaDataType = script_common.get_metadata(dataset_config)
    dataset_generator: KFoldDatasetGenerator = script_common.get_dataset_generator(
        metadata=metadata,
        dataset_config=dataset_config,
        mel_spec_config=mel_spec_config)
    for curr_val_fold in range(dataset_config.k_folds):
        curr_val_skm_path_stub: str = skl_skm_laoder.get_curr_val_skm_path_stub(
            curr_val_fold=curr_val_fold,
            skm_root_path=skm_root_path,
            val_fold_path_stub=val_fold_path_stub,
            class_skm_path_stub=class_skm_path_stub)
        skms: Sequence[SphericalKMeans] = skl_skm_laoder.load_skl_skms(
            curr_val_skm_path_stub=curr_val_skm_path_stub,
            n_classes=dataset_config.n_classes)
        collate_func: CollateFuncType = collate_base.EnsembleCollateFunction(
            collate_funcs=[
                partial(collate_transform.mel_spectrogram_collate,
                        config=mel_spec_config),
                partial(collate_reshape.slice_flatten_collate,
                        config=reshape_config),
                partial(collate_skm.skm_skl_proj_collate, skms=skms),
                partial(collate_pool.pool_collate,
                        pool_func=feature_pool.MeanStdPool(),
                        pool_config=pool_config)
            ])
        train, val = train_common.generate_proj_dataset(
            curr_val_fold=curr_val_fold,
            dataset_generator=dataset_generator,
            collate_function=collate_func,
            loader_config=loader_config)
        pca, train_slices, train_labels = train_pca_proj.fit_transform_pca(
            curr_val_fold=curr_val_fold,
            train=train,
            pca_config=pca_config,
            export_path=export_path)
        svc: SVC = train_common.train_svc_np(curr_val_fold=curr_val_fold,
                                             train_slices=train_slices,
                                             train_labels=train_labels,
                                             svc_config=svc_config,
                                             export_path=export_path)
        val_slices, val_labels = train_pca_proj.transform_pca(dataset=val,
                                                              pca=pca)
        train_common.report_slices_acc_np(svc=svc,
                                          train_slices=train_slices,
                                          train_labels=train_labels,
                                          val_slices=val_slices,
                                          val_labels=val_labels)


if __name__ == "__main__":
    args: List[str] = sys.argv[1:]
    main(args)