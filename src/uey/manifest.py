from pydantic import BaseModel, ConfigDict

class Column(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str
    data_type: str | None


# class ModelNode(BaseModel):
#     model_config = ConfigDict(extra="ignore")

#     unique_id: str
#     name: str
#     resource_type: str
#     access: str
#     database: str
#     schema: str
#     alias: str
#     relation_name: str
#     description: str
#     columns: str
#     version: str
#     latest_version: str

# class Manifest(BaseModel):
#     model_config = ConfigDict(extra="ignore")

#     project_name: str
#     dbt_schema_version: str
