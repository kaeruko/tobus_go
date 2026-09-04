use crate::model::{Itinerary, Leg};

pub fn reconstruct(
    predecessor: &[Option<(usize, Leg)>],
    state_index: usize,
    departure_minute: u32,
    arrival_minute: u32,
) -> Itinerary {
    let mut legs = Vec::new();
    let mut cursor = state_index;
    while let Some((previous, leg)) = &predecessor[cursor] {
        legs.push(leg.clone());
        cursor = *previous;
    }
    legs.reverse();
    Itinerary {
        departure_minute,
        arrival_minute,
        legs,
    }
}
