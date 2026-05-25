from pydantic import BaseModel as _PydanticBaseModel, ConfigDict


class BaseModel(_PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
