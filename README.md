## Background

Krünter is a infographics tool used for geographical analysis for the purpose
of evaluating plots of land in Harjumaa Estonia from various perspectives. E.g
* Home buyer
* Real estate developer
* Architect

Each group has a specific criteria in based on which they evaluate the land
Home buyers usually want to know what the surrounding environment has to offer
* Stores 
* Schools 
* Public transport possibilities
* Parks

Real estate developers would need to know the cost effectiveness of certain plots.
Krünter creates a detailplaneeringu analysis taking into account:
* The geological sediment in the area/ground - Can affect building cost
* Landscaping area
* Heritage conservation areas (muinsuskaitsealad)

Architects need to have a quick overview of requirements and surrounding personality of the plot:
* Noise level
* Winds
* Traffic analysis  


## Developing
```
poetry install
poetry shell
```
Start backend dev
`uvicorn backend.main:app --reload`

Start frontend dev
`cd frontend && npm run dev`

Open up the frontend URL and youre good to go