"""
Class to represent a layer of a configuration state to visualize images in neuroglancer
"""
from pathlib import Path
from typing import Dict, List, Optional, Union, get_args

import numpy as np

# IO types
PathLike = Union[str, Path]
SourceLike = Union[PathLike, List[Dict]]


def helper_create_ng_translation_matrix(
    delta_x: Optional[float] = 0,
    delta_y: Optional[float] = 0,
    delta_z: Optional[float] = 0,
    n_cols: Optional[int] = 6,
    n_rows: Optional[int] = 5,
) -> List:
    """
    Helper function to create the translation matrix based on deltas over each axis

    Parameters
    ------------------------
    delta_x: Optional[float]
        Translation over the x axis.
    delta_y: Optional[float]
        Translation over the y axis.
    delta_z: Optional[float]
        Translation over the z axis.
    n_cols: Optional[int]
        number of columns to create the translation matrix.
    n_rows: Optional[int]
        number of rows to create the translation matrix.

    Raises
    ------------------------
    ValueError:
        Raises if the N size of the transformation matrix is not
        enough for the deltas.

    Returns
    ------------------------
    List
        List with the translation matrix
    """

    translation_matrix = np.zeros((n_rows, n_cols), np.float16)
    np.fill_diagonal(translation_matrix, 1)

    deltas = [delta_x, delta_y, delta_z]
    start_point = n_rows - 1

    if start_point < len(deltas):
        raise ValueError(
            "N size of transformation matrix is not enough for deltas"
        )

    # Setting translations for axis
    for delta in deltas:
        translation_matrix[start_point][-1] = delta
        start_point -= 1

    return translation_matrix.tolist()


def helper_reverse_dictionary(dictionary: dict) -> dict:
    """
    Helper to reverse a dictionary

    Parameters
    ------------------------
    dictionary: dict
        Dictionary to reverse

    Returns
    ------------------------
    dict
        Reversed dictionary
    """

    keys = list(dictionary.keys())
    values = list(dictionary.values())
    new_dict = {}

    for idx in range(len(keys) - 1, -1, -1):
        new_dict[keys[idx]] = values[idx]

    return new_dict


class NgLayer:
    """
    Class to represent a neuroglancer layer in the configuration json
    """

    def __init__(
        self,
        image_config: dict,
        mount_service: str,
        bucket_path: str,
        image_type: Optional[str] = "image",
        output_dimensions: Optional[dict] = None,
    ) -> None:
        """
        Class constructor

        Parameters
        ------------------------
        image_config: dict
            Dictionary with the image configuration based on neuroglancer documentation.
        mount_service: Optional[str]
            This parameter could be 'gs' referring to a bucket in Google Cloud or 's3'in Amazon.
        bucket_path: str
            Path in cloud service where the dataset will be saved
        image_type: Optional[str]
            Image type based on neuroglancer documentation.

        """

        self.__layer_state = {}
        self.image_config = image_config
        self.mount_service = mount_service
        self.bucket_path = bucket_path
        self.image_type = image_type

        # Optional parameter that must be used when we have multiple images per layer
        # Dictionary needs to be reversed for correct visualization
        self.output_dimensions = helper_reverse_dictionary(output_dimensions)

        # Fix image source
        self.image_source = self.__fix_image_source(image_config["source"])
        image_config["source"] = self.image_source

        self.update_state(image_config)

    def __set_s3_path(self, orig_source_path: PathLike) -> str:
        """
        Private method to set a s3 path based on a source path.
        Available image formats: ['.zarr']

        Parameters
        ------------------------
        orig_source_path: PathLike
            Source path of the image

        Raises
        ------------------------
        NotImplementedError:
            Raises if the image format is not zarr.

        Returns
        ------------------------
        str
            String with the source path pointing to the mount service in the cloud
        """

        s3_path = None
        if not orig_source_path.startswith(f"{self.mount_service}://"):
            orig_source_path = Path(orig_source_path)
            s3_path = (
                f"{self.mount_service}://{self.bucket_path}/{orig_source_path}"
            )

        else:
            s3_path = orig_source_path

        if s3_path.endswith(".zarr"):
            s3_path = "zarr://" + s3_path

        else:
            raise NotImplementedError(
                "This format has not been implemented yet for visualization"
            )

        return s3_path

    def __set_sources_paths(self, sources_paths: List) -> List:
        """
        Private method to set multiple image sources on s3 path. It also accepts
        a transformation matrix that should be provided in the form of a list for
        or a affine transformation or dictionary for a translation matrix.
        Available image formats: ['.zarr']

        Parameters
        ------------------------
        sources_paths: List
            List of dictionaries with the image sources and its transformation
            matrices in the case they are provided.

        Returns
        ------------------------
        List
            List of dictionaries with the configuration for neuroglancer
        """
        new_source_path = []

        for source in sources_paths:
            new_dict = {}

            for key in source.keys():
                if key == "transform_matrix" and isinstance(
                    source["transform_matrix"], dict
                ):
                    new_dict["transform"] = {
                        "matrix": helper_create_ng_translation_matrix(
                            delta_x=source["transform_matrix"]["delta_x"],
                            delta_y=source["transform_matrix"]["delta_y"],
                            delta_z=source["transform_matrix"]["delta_z"],
                        ),
                        "outputDimensions": self.output_dimensions,
                    }

                elif key == "transform_matrix" and isinstance(
                    source["transform_matrix"], list
                ):
                    new_dict["transform"] = {
                        "matrix": source["transform_matrix"],
                        "outputDimensions": self.output_dimensions,
                    }

                elif key == "url":
                    new_dict["url"] = self.__set_s3_path(source["url"])

                else:
                    new_dict[key] = source[key]

            new_source_path.append(new_dict)

        return new_source_path

    def __fix_image_source(self, source_path: SourceLike) -> str:
        """
        Fixes the image source path to include the type of image neuroglancer accepts.

        Parameters
        ------------------------
        source_path: SourceLike
            Path or list of paths where the images are located with their transformation matrix.

        Returns
        ------------------------
        SourceLike
            Fixed path(s) for neuroglancer json configuration.
        """
        new_source_path = None

        if isinstance(source_path, list):
            # multiple sources in single image
            new_source_path = self.__set_sources_paths(source_path)

        elif isinstance(source_path, get_args(PathLike)):
            # Single source image
            new_source_path = self.__set_s3_path(source_path)

        return new_source_path

    # flake8: noqa: C901
    def set_default_values(
        self, image_config: dict = {}, overwrite: bool = False
    ) -> None:
        """
        Set default values for the image.

        Parameters
        ------------------------
        image_config: dict
            Dictionary with the image configuration. Similar to self.image_config

        overwrite: bool
            If the parameters already have values, with this flag they can be overwritten.

        """

        if overwrite:
            self.image_channel = 0
            self.shader_control = {"normalized": {"range": [0, 200]}}
            self.visible = True
            self.__layer_state["name"] = str(Path(self.image_source).stem)
            self.__layer_state["type"] = str(self.image_type)

        elif len(image_config):
            # Setting default image_config in json image layer
            if "channel" not in image_config:
                # Setting channel to 0 for image
                self.image_channel = 0

            if "shaderControls" not in image_config:
                self.shader_control = {"normalized": {"range": [0, 200]}}

            if "visible" not in image_config:
                self.visible = True

            if "name" not in image_config:
                try:
                    channel = self.__layer_state["localDimensions"]["c'"][0]

                except KeyError:
                    channel = ""

                if isinstance(self.image_source, get_args(PathLike)):
                    self.__layer_state[
                        "name"
                    ] = f"{Path(self.image_source).stem}_{channel}"

                else:
                    self.__layer_state[
                        "name"
                    ] = f"{Path(self.image_source[0]['url']).stem}_{channel}"

            if "type" not in image_config:
                self.__layer_state["type"] = str(self.image_type)

    # flake8: noqa: C901
    def update_state(self, image_config: dict) -> None:
        """
        Set default values for the image.

        Parameters
        ------------------------
        image_config: dict
            Dictionary with the image configuration. Similar to self.image_config
            e.g.: image_config = {
                'type': 'image', # Optional
                'source': 'image_path',
                'channel': 0, # Optional
                'name': 'image_name', # Optional
                'shader': {
                    'color': 'green',
                    'emitter': 'RGB',
                    'vec': 'vec3'
                },
                'shaderControls': { # Optional
                    "normalized": {
                        "range": [0, 200]
                    }
                }
            }
        """

        for param, value in image_config.items():
            if param in ["type", "name", "blend"]:
                self.__layer_state[param] = str(value)

            if param in ["visible"]:
                self.visible = value

            if param == "shader":
                self.shader = self.__create_shader(value)

            if param == "channel":
                self.image_channel = value

            if param == "shaderControls":
                self.shader_control = value

            if param == "opacity":
                self.opacity = value

            if param == "source":
                if isinstance(value, get_args(PathLike)):
                    self.__layer_state[param] = str(value)

                elif isinstance(value, list):
                    # Setting list of dictionaries with image configuration
                    self.__layer_state[param] = value

        self.set_default_values(image_config)

    def __create_shader(self, shader_config: dict) -> str:
        """
        Creates a configuration for the neuroglancer shader.

        Parameters
        ------------------------
        shader_config: dict
            Configuration of neuroglancer's shader.

        Returns
        ------------------------
        str
            String with the shader configuration for neuroglancer.
        """

        color = shader_config["color"]
        emitter = shader_config["emitter"]
        vec = shader_config["vec"]

        # Add all necessary ui controls here
        ui_controls = [
            f'#uicontrol {vec} color color(default="{color}")',
            "#uicontrol invlerp normalized",
        ]

        # color emitter
        emit_color = (
            "void main() {\n" + f"emit{emitter}(color * normalized());" + "\n}"
        )
        shader_string = ""

        for ui_control in ui_controls:
            shader_string += ui_control + "\n"

        shader_string += emit_color

        return shader_string

    @property
    def opacity(self) -> str:
        """
        Getter of the opacity property

        Returns
        ------------------------
        str
            String with the opacity value
        """
        return self.__layer_state["opacity"]

    @opacity.setter
    def opacity(self, opacity: float) -> None:
        """
        Sets the opacity parameter in neuroglancer link.

        Parameters
        ------------------------
        opacity: float
            Float number between [0-1] that indicates the opacity.

        Raises
        ------------------------
        ValueError:
            If the parameter is not an boolean.
        """
        self.__layer_state["opacity"] = float(opacity)

    @property
    def shader(self) -> str:
        """
        Getter of the shader property

        Returns
        ------------------------
        str
            String with the shader value
        """
        return self.__layer_state["shader"]

    @shader.setter
    def shader(self, shader_config: str) -> None:
        """
        Sets a configuration for the neuroglancer shader.

        Parameters
        ------------------------
        shader_config: str
            Shader configuration for neuroglancer in string format.
            e.g. #uicontrol vec3 color color(default=\"green\")\n#uicontrol invlerp normalized\nvoid main() {\n  emitRGB(color * normalized());\n}

        Raises
        ------------------------
        ValueError:
            If the provided shader_config is not a string.

        """
        self.__layer_state["shader"] = str(shader_config)

    @property
    def shader_control(self) -> dict:
        """
        Getter of the shader control property

        Returns
        ------------------------
        str
            String with the shader control value
        """
        return self.__layer_state["shaderControls"]

    @shader_control.setter
    def shader_control(self, shader_control_config: dict) -> None:
        """
        Sets a configuration for the neuroglancer shader control.

        Parameters
        ------------------------
        shader_control_config: dict
            Shader control configuration for neuroglancer.

        Raises
        ------------------------
        ValueError:
            If the provided shader_control_config is not a dictionary.

        """
        self.__layer_state["shaderControls"] = dict(shader_control_config)

    @property
    def image_channel(self) -> int:
        """
        Getter of the current image channel in the layer

        Returns
        ------------------------
        int
            Integer with the current image channel
        """
        return self.__layer_state["localDimensions"]["c"]

    @image_channel.setter
    def image_channel(self, channel: int) -> None:
        """
        Sets the image channel in case the file contains multiple channels.

        Parameters
        ------------------------
        channel: int
            Channel position. It will be incremented in 1 since neuroglancer channels starts in 1.

        Raises
        ------------------------
        ValueError:
            If the provided channel is not an integer.

        """
        self.__layer_state["localDimensions"] = {"c'": [int(channel) + 1, ""]}

    @property
    def visible(self) -> bool:
        """
        Getter of the visible attribute of the layer.
        True means the layer will be visible when the image
        is loaded in neuroglancer, False otherwise.

        Returns
        ------------------------
        bool
            Boolean with the current visible value
        """
        return self.__layer_state["visible"]

    @visible.setter
    def visible(self, visible: bool) -> None:
        """
        Sets the visible parameter in neuroglancer link.

        Parameters
        ------------------------
        visible: bool
            Boolean that dictates if the image is visible or not.

        Raises
        ------------------------
        ValueError:
            If the parameter is not an boolean.
        """
        self.__layer_state["visible"] = bool(visible)

    @property
    def layer_state(self) -> dict:
        """
        Getter of layer state property.

        Returns
        ------------------------
        dict:
            Dictionary with the current configuration of the layer state.
        """
        return self.__layer_state

    @layer_state.setter
    def layer_state(self, new_layer_state: dict) -> None:
        """
        Setter of layer state property.

        Parameters
        ------------------------
        new_layer_state: dict
            Dictionary with the new configuration of the layer state.
        """
        self.__layer_state = dict(new_layer_state)
