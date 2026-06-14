"""Shared field type definitions for templates and validation."""

from enum import Enum


class FieldType(str, Enum):
    name = "name"
    location = "location"
    gender = "gender"
    date = "date"
    string = "string"
    number = "number"
    phone = "phone"
    email = "email"
    college_name = "college_name"
    school_name = "school_name"
    company_name = "company_name"
    hobby = "hobby"
    address = "address"
    city = "city"
    country = "country"
    zip_code = "zip_code"
    id_number = "id_number"
    age = "age"
    occupation = "occupation"
    department = "department"
    title = "title"
    custom = "custom"


FIELD_TYPE_LABELS: dict[str, str] = {
    FieldType.name: "Name",
    FieldType.location: "Location",
    FieldType.gender: "Gender",
    FieldType.date: "Date",
    FieldType.string: "Text / string",
    FieldType.number: "Number",
    FieldType.phone: "Phone",
    FieldType.email: "Email",
    FieldType.college_name: "College name",
    FieldType.school_name: "School name",
    FieldType.company_name: "Company name",
    FieldType.hobby: "Hobby",
    FieldType.address: "Address",
    FieldType.city: "City",
    FieldType.country: "Country",
    FieldType.zip_code: "ZIP / postal code",
    FieldType.id_number: "ID number",
    FieldType.age: "Age",
    FieldType.occupation: "Occupation",
    FieldType.department: "Department",
    FieldType.title: "Title / position",
    FieldType.custom: "Custom",
}
