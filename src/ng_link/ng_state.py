"""
Class to represent a configuration state to visualize data in neuroglancer
"""
import re
from pathlib import Path
from typing import List, Optional, Union

import xmltodict
from pint import UnitRegistry


from .ng_layer import NgLayer
from .utils import utils

# IO types
PathLike = Union[str, Path]

#Added for example 3
import os
import json
import time
import struct
import random
import inspect
import neuroglancer
import multiprocessing
import numpy as np
import pandas as pd
from multiprocessing.managers import NamespaceProxy, BaseManager

#Added for example 4
import boto3
from glob import glob

class NgState:
    """
    Class to represent a neuroglancer state (configuration json)
    """

    def __init__(
        self,
        input_config: dict,
        mount_service: str,
        bucket_path: str,
        output_json: PathLike,
        verbose: Optional[bool] = False,
        base_url: Optional[str] = "https://neuroglancer-demo.appspot.com/",
        json_name: Optional[str] = "process_output.json",
    ) -> None:
        """
        Class constructor

        Parameters
        ------------------------
        image_config: dict
            Dictionary with the json configuration based on neuroglancer docs.
        mount_service: Optional[str]
            Could be 'gs' for a bucket in Google Cloud or 's3' in Amazon.
        bucket_path: str
            Path in cloud service where the dataset will be saved
        output_json: PathLike
            Path where the json will be written.
        verbose: Optional[bool]
            If true, additional information will be shown. Default False.
        base_url: Optional[str]
            Neuroglancer service url
        json_name: Optional[str]
            Name of json file with neuroglancer configuration

        """

        self.input_config = input_config
        self.output_json = Path(self.__fix_output_json_path(output_json))
        self.verbose = verbose
        self.mount_service = mount_service
        self.bucket_path = bucket_path
        self.base_url = base_url
        self.json_name = json_name

        # State and layers attributes
        self.__state = {}
        self.__dimensions = {}
        self.__layers = []

        # Initialize principal attributes
        self.initialize_attributes(self.input_config)

    def __fix_output_json_path(self, output_json: PathLike) -> str:

        """
        Fixes the json output path to have a similar structure for all links.

        Parameters
        ------------------------
        output_json: PathLike
            Path of the json output path.

        Returns
        ------------------------
        str
            String with the fixed outputh path.
        """
        output_json = Path(
            str(output_json)
            .replace("/home/jupyter/", "")
            .replace("////", "//")
        )

        return output_json

    def __unpack_axis(
        self, axis_values: dict, dest_metric: Optional[str] = "meters"
    ) -> List:
        """
        Unpack axis voxel sizes converting them to meters.
        neuroglancer uses meters by default.

        Parameters
        ------------------------
        axis_values: dict
            Dictionary with the axis values with
            the following structure for an axis:
            e.g. for Z dimension {
                "voxel_size": 2.0,
                "unit": 'microns'
            }

        dest_metric: Optional[str]
            Destination metric to be used in neuroglancer. Default 'meters'.

        Returns
        ------------------------
        List
            List with two values, the converted quantity
            and it's metric in neuroglancer format.
        """

        if dest_metric not in ["meters", "seconds"]:
            raise NotImplementedError(
                f"{dest_metric} has not been implemented"
            )

        # Converting to desired metric
        unit_register = UnitRegistry()
        quantity = (
            axis_values["voxel_size"] * unit_register[axis_values["unit"]]
        )
        dest_quantity = quantity.to(dest_metric)

        # Neuroglancer metric
        neuroglancer_metric = None
        if dest_metric == "meters":
            neuroglancer_metric = "m"

        elif dest_metric == "seconds":
            neuroglancer_metric = "s"

        return [dest_quantity.m, neuroglancer_metric]

    @property
    def dimensions(self) -> dict:
        """
        Property getter of dimensions.

        Returns
        ------------------------
        dict
            Dictionary with neuroglancer dimensions' configuration.
        """
        return self.__dimensions

    @dimensions.setter
    def dimensions(self, new_dimensions: dict) -> None:

        """
        Set dimensions with voxel sizes for the image.

        Parameters
        ------------------------
        dimensions: dict
            Dictionary with the axis values
            with the following structure for an axis:
            e.g. for Z dimension {
                "voxel_size": 2.0,
                "unit": 'microns'
            }

        """

        if not isinstance(new_dimensions, dict):
            raise ValueError(
                f"Dimensions accepts only dict. Received: {new_dimensions}"
            )

        regex_axis = r"([x-zX-Z])$"

        for axis, axis_values in new_dimensions.items():

            if re.search(regex_axis, axis):
                self.__dimensions[axis] = self.__unpack_axis(axis_values)
            elif axis == "t":
                self.__dimensions[axis] = self.__unpack_axis(
                    axis_values, "seconds"
                )
            elif axis == "c'":
                self.__dimensions[axis] = [
                    axis_values["voxel_size"],
                    axis_values["unit"],
                ]

    @property
    def layers(self) -> List[dict]:
        """
        Property getter of layers.

        Returns
        ------------------------
        List[dict]
            List with neuroglancer layers' configuration.
        """
        return self.__layers

    @layers.setter
    def layers(self, layers: List[dict]) -> None:
        """
        Property setter of layers.

        Parameters
        ------------------------
        layers: List[dict]
            List that contains a configuration for each image layer.

        """

        if not isinstance(layers, list):
            raise ValueError(
                f"layers accepts only list. Received value: {layers}"
            )

        for layer in layers:
            config = {}

            if layer["type"] == "image":
                config = {
                    "image_config": layer,
                    "mount_service": self.mount_service,
                    "bucket_path": self.bucket_path,
                    "output_dimensions": self.dimensions,
                    "layer_type": layer["type"],
                }

            elif layer["type"] == "annotation":
                config = {
                    "annotation_source": layer["source"],
                    "annotation_locations": layer["annotations"],
                    "layer_type": layer["type"],
                    "output_dimensions": self.dimensions,
                    "limits": layer["limits"] if "limits" in layer else None,
                }
                
            #changed to work with library notation NL
            self.__layers.append(NgLayer().create(config).layer_state)

    @property
    def state(self, new_state: dict) -> None:
        """
        Property setter of state.

        Parameters
        ------------------------
        input_config: dict
            Dictionary with the configuration for the neuroglancer state

        """
        self.__state = dict(new_state)

    @state.getter
    def state(self) -> dict:
        """
        Property getter of state.

        Returns
        ------------------------
        dict
            Dictionary with the actual layer state.
        """

        actual_state = {}
        actual_state["ng_link"] = self.get_url_link()
        actual_state["dimensions"] = {}

        # Getting actual state for all attributes
        for axis, value_list in self.__dimensions.items():
            actual_state["dimensions"][axis] = value_list

        actual_state["layers"] = self.__layers

        actual_state["showAxisLines"] = True
        actual_state["showScaleBar"] = True

        return actual_state

    def initialize_attributes(self, input_config: dict) -> None:
        """
        Initializes the following attributes for a given
        image layer: dimensions, layers.

        Parameters
        ------------------------
        input_config: dict
            Dictionary with the configuration for each image layer

        """

        # Initializing dimension
        self.dimensions = input_config["dimensions"]

        # Initializing layers
        self.layers = input_config["layers"]

        # Initializing state
        self.__state = self.state

        for key, val in input_config.items():
            if key == "showAxisLines":
                self.show_axis_lines = val

            elif key == "showScaleBar":
                self.show_scale_bar = val

    @property
    def show_axis_lines(self) -> bool:
        """
        Getter of the show axis lines property

        Returns
        ------------------------
        bool
            Boolean with the show axis lines value.
        """
        return self.__state["showAxisLines"]

    @show_axis_lines.setter
    def show_axis_lines(self, new_show_axis_lines: bool) -> None:
        """
        Sets the visible parameter in neuroglancer link.

        Parameters
        ------------------------
        new_show_axis_lines: bool
            Boolean that dictates if the image axis are visible or not.

        Raises
        ------------------------
        ValueError:
            If the parameter is not an boolean.
        """
        self.__state["showAxisLines"] = bool(new_show_axis_lines)

    @property
    def show_scale_bar(self) -> bool:
        """
        Getter of the show scale bar property

        Returns
        ------------------------
        bool
            Boolean with the show scale bar value.
        """
        return self.__state["showScaleBar"]

    @show_scale_bar.setter
    def show_scale_bar(self, new_show_scale_bar: bool) -> None:
        """
        Sets the visible parameter in neuroglancer link.

        Parameters
        ------------------------
        new_show_scale_bar: bool
            Boolean that dictates if the image scale bar are visible or not.

        Raises
        ------------------------
        ValueError:
            If the parameter is not an boolean.
        """
        self.__state["showScaleBar"] = bool(new_show_scale_bar)

    def save_state_as_json(self, update_state: Optional[bool] = False) -> None:
        """
        Saves a neuroglancer state as json.

        Parameters
        ------------------------
        update_state: Optional[bool]
            Updates the neuroglancer state with dimensions
            and layers in case they were changed using
            class methods. Default False
        """

        if update_state:
            self.__state = self.state

        final_path = Path(self.output_json).joinpath(self.json_name)
        utils.save_dict_as_json(final_path, self.__state, verbose=self.verbose)

    def get_url_link(self) -> str:
        """
        Creates the neuroglancer link based on where the json will be written.

        Returns
        ------------------------
        str
            Neuroglancer url to visualize data.
        """

        dataset_name = Path(self.output_json.stem)

        json_path = str(dataset_name.joinpath(self.json_name))
        json_path = f"{self.mount_service}://{self.bucket_path}/{json_path}"

        link = f"{self.base_url}#!{json_path}"

        return link


def get_points_from_xml(path: PathLike, encoding: str = "utf-8") -> List[dict]:
    """
    Function to parse the points from the
    cell segmentation capsule.

    Parameters
    -----------------

    Path: PathLike
        Path where the XML is stored.

    encoding: str
        XML encoding. Default: "utf-8"

    Returns
    -----------------
    List[dict]
        List with the location of the points.
    """

    with open(path, "r", encoding=encoding) as xml_reader:
        xml_file = xml_reader.read()

    xml_dict = xmltodict.parse(xml_file)
    cell_data = xml_dict["CellCounter_Marker_File"]["Marker_Data"][
        "Marker_Type"
    ]["Marker"]

    new_cell_data = []
    for cell in cell_data:
        new_cell_data.append(
            {
                "x": cell["MarkerX"],
                "y": cell["MarkerY"],
                "z": cell["MarkerZ"],
            }
        )

    return new_cell_data


#==============================================================================
# paralell functions
#==============================================================================

class ObjProxy(NamespaceProxy):
    """Returns a proxy instance for any user defined data-type. The proxy instance will have the namespace and
    functions of the data-type (except private/protected callables/attributes). Furthermore, the proxy will be
    pickable and can its state can be shared among different processes. """

    @classmethod
    def populate_obj_attributes(cls, real_cls):
        DISALLOWED = set(dir(cls))
        ALLOWED = ['__sizeof__', '__eq__', '__ne__', '__le__', '__repr__', '__dict__', '__lt__',
                   '__gt__']
        DISALLOWED.add('__class__')
        new_dict = {}
        for (attr, value) in inspect.getmembers(real_cls, callable):
            if attr not in DISALLOWED or attr in ALLOWED:
                new_dict[attr] = cls._proxy_wrap(attr)
        return new_dict

    @staticmethod
    def _proxy_wrap(attr):
        """ This method creates function that calls the proxified object's method."""

        def f(self, *args, **kwargs):
            return self._callmethod(attr, args, kwargs)

        return f

def buf_builder(x, y, z, buf_):
    pt_buf = struct.pack('<3f', x, y, z)
    buf_.extend(pt_buf)



def example_1():
    """
    Example one related to the SmartSPIM data
    """
    example_data = {
        "dimensions": {
            # check the order
            "z": {"voxel_size": 2.0, "unit": "microns"},
            "y": {"voxel_size": 1.8, "unit": "microns"},
            "x": {"voxel_size": 1.8, "unit": "microns"},
            "t": {"voxel_size": 0.001, "unit": "seconds"},
        },
        "layers": [
            {
                "source": "image_path.zarr",
                "type": "image",
                "channel": 0,
                # 'name': 'image_name_0',
                "shader": {"color": "green", "emitter": "RGB", "vec": "vec3"},
                "shaderControls": {  # Optional
                    "normalized": {"range": [0, 500]}
                },
            },
            {
                "source": "image_path.zarr",
                "type": "image",
                "channel": 1,
                # 'name': 'image_name_1',
                "shader": {"color": "red", "emitter": "RGB", "vec": "vec3"},
                "shaderControls": {  # Optional
                    "normalized": {"range": [0, 500]}
                },
            },
        ],
    }

    neuroglancer_link = NgState(
        input_config=example_data,
        mount_service="s3",
        bucket_path="aind-msma-data",
        output_json="/Users/camilo.laiton/repositories/aind-ng-link/src",
    )

    data = neuroglancer_link.state
    print(data)
    # neuroglancer_link.save_state_as_json('test.json')
    neuroglancer_link.save_state_as_json()
    print(neuroglancer_link.get_url_link())


def example_2():
    """
    Example 2 related to the ExaSPIM data
    """
    example_data = {
        "dimensions": {
            # check the order
            "x": {"voxel_size": 0.74800002019210531934, "unit": "microns"},
            "y": {"voxel_size": 0.74800002019210531934, "unit": "microns"},
            "z": {"voxel_size": 1, "unit": "microns"},
            "c'": {"voxel_size": 1, "unit": ""},
            "t": {"voxel_size": 0.001, "unit": "seconds"},
        },
        "layers": [
            {
                "type": "image",  # Optional
                "source": [
                    {
                        "url": "s3://aind-open-data/exaSPIM_609107_2022-09-21_14-48-48/exaSPIM/tile_x_0000_y_0000_z_0000_ch_488.zarr",
                        "transform_matrix": {
                            "delta_x": -14192,
                            "delta_y": -10640,
                            "delta_z": 0,
                        },
                    },
                    {
                        "url": "s3://aind-open-data/exaSPIM_609107_2022-09-21_14-48-48/exaSPIM/tile_x_0000_y_0001_z_0000_ch_488.zarr",
                        "transform_matrix": {
                            "delta_x": -14192,
                            "delta_y": -19684.000456947142,
                            "delta_z": 0,
                        },
                    },
                    {
                        "url": "s3://aind-open-data/exaSPIM_609107_2022-09-21_14-48-48/exaSPIM/tile_x_0000_y_0002_z_0000_ch_488.zarr",
                        "transform_matrix": {
                            "delta_x": -14192,
                            "delta_y": -28727.998694435275,
                            "delta_z": 0,
                        },
                    },
                    {
                        "url": "s3://aind-open-data/exaSPIM_609107_2022-09-21_14-48-48/exaSPIM/tile_x_0001_y_0000_z_0000_ch_488.zarr",
                        "transform_matrix": {
                            "delta_x": -26255.200652782467,
                            "delta_y": -10640,
                            "delta_z": 0,
                        },
                    },
                    {
                        "url": "s3://aind-open-data/exaSPIM_609107_2022-09-21_14-48-48/exaSPIM/tile_x_0001_y_0001_z_0000_ch_488.zarr",
                        "transform_matrix": {
                            "delta_x": -26255.200652782467,
                            "delta_y": -19684.000456947142,
                            "delta_z": 0,
                        },
                    },
                    {
                        "url": "s3://aind-open-data/exaSPIM_609107_2022-09-21_14-48-48/exaSPIM/tile_x_0001_y_0002_z_0000_ch_488.zarr",
                        "transform_matrix": {
                            "delta_x": -26255.200652782467,
                            "delta_y": -28727.998694435275,
                            "delta_z": 0,
                        },
                    },
                    {
                        "url": "s3://aind-open-data/exaSPIM_609107_2022-09-21_14-48-48/exaSPIM/tile_x_0002_y_0000_z_0000_ch_488.zarr",
                        "transform_matrix": {
                            "delta_x": -38318.39686664473,
                            "delta_y": -10640,
                            "delta_z": 0,
                        },
                    },
                    {
                        "url": "s3://aind-open-data/exaSPIM_609107_2022-09-21_14-48-48/exaSPIM/tile_x_0002_y_0001_z_0000_ch_488.zarr",
                        "transform_matrix": {
                            "delta_x": -38318.39686664473,
                            "delta_y": -19684.000456947142,
                            "delta_z": 0,
                        },
                    },
                    {
                        "url": "s3://aind-open-data/exaSPIM_609107_2022-09-21_14-48-48/exaSPIM/tile_x_0002_y_0002_z_0000_ch_488.zarr",
                        "transform_matrix": {
                            "delta_x": -38318.39686664473,
                            "delta_y": -28727.998694435275,
                            "delta_z": 0,
                        },
                    },
                    {
                        "url": "s3://aind-open-data/exaSPIM_609107_2022-09-21_14-48-48/exaSPIM/tile_x_0003_y_0000_z_0000_ch_488.zarr",
                        "transform_matrix": {
                            "delta_x": -50381.5952999671,
                            "delta_y": -10640,
                            "delta_z": 0,
                        },
                    },
                    {
                        "url": "s3://aind-open-data/exaSPIM_609107_2022-09-21_14-48-48/exaSPIM/tile_x_0003_y_0001_z_0000_ch_488.zarr",
                        "transform_matrix": {
                            "delta_x": -50381.5952999671,
                            "delta_y": -19684.000456947142,
                            "delta_z": 0,
                        },
                    },
                    {
                        "url": "s3://aind-open-data/exaSPIM_609107_2022-09-21_14-48-48/exaSPIM/tile_x_0003_y_0002_z_0000_ch_488.zarr",
                        "transform_matrix": {
                            "delta_x": -50381.5952999671,
                            "delta_y": -28727.998694435275,
                            "delta_z": 0,
                        },
                    },
                ],
                "channel": 0,  # Optional
                "shaderControls": {  # Optional
                    "normalized": {"range": [30, 70]}
                },
                "visible": True,  # Optional
                "opacity": 0.50,
            },
            {
                "type": "annotation",  # Optional
                "source": {"url": "local://annotations"},
                "tool": "annotatePoint",
                "name": "annotation_name_layer",
                "annotations": [
                    [1865, 4995, 3646, 0.5, 0.5],
                    [1865, 4985, 3641, 0.5, 0.5],
                ],
            },
        ],
        "showScaleBar": False,
        "showAxisLines": False,
    }

    neuroglancer_link = NgState(
        input_config=example_data,
        mount_service="s3",
        bucket_path="aind-msma-data",
        output_json="/Users/camilo.laiton/repositories/aind-ng-link/src",
    )

    data = neuroglancer_link.state
    # print(data)
    neuroglancer_link.save_state_as_json()
    print(neuroglancer_link.get_url_link())


def example_3(cells, path, res, buf = None):
    """
    Function for saving precomputed annotation layer

    Parameters
    -----------------

    cells: dict
        output of the xmltodict function for importing cell locations
    path: str
        path to where you want to save the precomputed files
    res: neuroglancer.CoordinateSpace()
        data on the space that the data will be viewed
    buf: bytearrayProxy object
        if you want to use multiprocessing set to bytearrayProxy object else 
        leave as None
        
    """
    
    cell_list = []
    for cell in cells:
        cell_list.append([int(cell['z']), int(cell['y']), int(cell['x'])])
    
    l_bounds = np.min(cell_list, axis = 0)
    u_bounds = np.max(cell_list, axis = 0)
    
    metadata = {
        '@type': 'neuroglancer_annotations_v1',
        'dimensions': res.to_json(),
        'lower_bound': [float(x) for x in l_bounds],
        'upper_bound': [float(x) for x in u_bounds],
        'annotation_type':'point',
        "properties" : [],
        "relationships" : [],
        'by_id': {'key': 'by_id',},
        'spatial': [
            {
                'key': 'spatial0',
                'grid_shape': [1] * res.rank,
                'chunk_size': [max(1, float(x)) for x in u_bounds - l_bounds],
                'limit': len(cells),
            },
        ],
    }
    
    with open(os.path.join(path, 'info'), 'w') as f:
        f.write(json.dumps(metadata))
    
   
    with open(os.path.join(path, 'spatial0', '0_0_0'),'wb') as outfile:
        
        start_t = time.time()
        
        total_count=len(cell_list) # coordinates is a list of tuples (x,y,z) 

        
        print("Running multiprocessing")
        
        if not isinstance(buf, type(None)):
            
            buf.extend(struct.pack('<Q',total_count))
            
            with multiprocessing.Pool(processes = os.cpu_count()) as p:
                p.starmap(buf_builder, [(x, y, z, buf) for (x, y, z) in cell_list])
                
            # write the ids at the end of the buffer as increasing integers 
            id_buf = struct.pack('<%sQ' % len(cell_list), *range(len(cell_list)))
            buf.extend(id_buf)
        else:
            
            buf = struct.pack('<Q',total_count)
            
            for (x,y,z) in cell_list:
                pt_buf = struct.pack('<3f',x,y,z)
                buf += pt_buf
                
            # write the ids at the end of the buffer as increasing integers 
            id_buf = struct.pack('<%sQ' % len(cell_list), *range(len(cell_list)))
            buf += id_buf
            
        print("Building file took {0} minutes".format((time.time() - start_t) / 60))
        
        outfile.write(bytes(buf))

def get_ccf(out_path):
    """
    Parameters
    ----------
    out_path : str
        path to where the precomputed segmentation map will be stored

    Returns
    -------
    None.

    """
    
    # location of the data from tissueCyte, but can get our own and change to aind-open-data
    bucketName = 'tissuecyte-visualizations'
    s3_folder = 'data/221205/ccf_annotations/'
    
    s3_resource = boto3.resource('s3')
    bucket = s3_resource.Bucket(bucketName) 
    
    for obj in bucket.objects.filter(Prefix = s3_folder):
        target = os.path.join(out_path, os.path.relpath(obj.key, s3_folder))
        
        # dont currently need 10um data so we should skip
        if '10000_10000_10000' in obj.key:
            continue
        
        if not os.path.exists(os.path.dirname(target)):
            os.makedirs(os.path.dirname(target))

        # dont try and download folders
        if obj.key[-1] == '/':
            continue

        bucket.download_file(obj.key, target)


def example_4(input_path, output_path):
    
    """
    Function for creating segmentation layer with cell counts

    Parameters
    -----------------

    input_path: str
        path to file from "aind_SmartSPIM_quantification". named "Cell_count_by_region.csv"
    output_path: str
        path to where you want to save the precomputed files
    """
    #check that save path exists and if not create
    if not os.path.exists(output_path):
        os.mkdir(output_path)
    
    # import count data
    count_file = glob(os.path.join(input_path, '*_by_region.csv'))[0]
    
    df_count = pd.read_csv(count_file, index_col = 0)
    include = list(df_count['Structure'].values)
        
    # get CCF id-struct pairings
    df_ccf = pd.read_csv('./data/ccf_ref.csv')
        
    keep_ids = []
    keep_struct = []
    for r, irow in df_ccf.iterrows():
        if irow['struct'] in include:
            keep_ids.append(str(irow['id']))
            total = df_count.loc[df_count['Structure'] == irow['struct'], ['Total']].values.squeeze()
            keep_struct.append(irow['struct'] + ' cells: ' + str(total))
    
    # download ccf procomputed format
    get_ccf(output_path)
    
    # currently using 25um resolution so need to drop 10um data or NG finicky
    with open(os.path.join(output_path, "info"), "r") as f:
        info_file = json.load(f)
    
    info_file['scales'].pop(0)
    
    with open(os.path.join(output_path, "info"), "w") as f:
        json.dump(info_file, f, indent = 2)
    
    
    # build json for segmantation properties
    data = {
        "@type": "neuroglancer_segment_properties",
        'inline': {
            "ids": keep_ids,
            "properties": [
                {
                    "id": "label",
                    "type": "label",
                    "values": keep_struct
                    }
                ]
            }
        }
        
    with open(os.path.join(output_path, "segment_properties/info"), "w") as outfile:
        json.dump(data, outfile, indent = 2)

# flake8: noqa: E501
def examples(buf):
    """
    Examples of how to use the neurglancer state class.
    """

    #location of segmentatio output and preprocessing for better visualization
    cells_path = "/path/to/detected_cells.xml"
    cells = get_points_from_xml(cells_path)
    cells = random.shuffle(cells)
    
    #saving parameters
    save_path = ""
    res = neuroglancer.CoordinateSpace(
            names=['z', 'y', 'x'],
            units=['um', 'um', 'um'],
            scales=[2, 1.8, 1.8])
    
    example_3(cells, save_path, res, buf)
    
    return

attributes = ObjProxy.populate_obj_attributes(bytearray)
bytearrayProxy = type("bytearrayProxy", (ObjProxy,), attributes)

if __name__ == "__main__":
    
    #uncomment to run example 3
    
    # #set up manager for multiprocessing write directory
    # BaseManager.register('bytearray', bytearray, bytearrayProxy, exposed=tuple(dir(bytearrayProxy)))
    # manager = BaseManager()
    # manager.start()
    # buf = manager.bytearray()
    
    # examples(buf)
    
    
    #uncomment to run example 4
    input_path = '/path/to/cell/count/data'
    save_path = '/path/to/segmentation/folder'
    
    example_4(input_path, save_path)
    
    
